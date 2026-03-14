import json
import os
import time
import uuid
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
s3 = boto3.client("s3")

TABLE_NAME = os.getenv("TABLE_NAME")
QUEUE_URL = os.getenv("QUEUE_URL")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET")

MAX_TEXT_LENGTH = 5000
ALLOWED_VOICES = {"male", "female"}
DEFAULT_USER_ID = "demo"
TTL_SECONDS = 24 * 60 * 60
PRESIGN_EXPIRES = 900


def json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def get_table():
    if not TABLE_NAME:
        raise RuntimeError("TABLE_NAME environment variable is missing")
    return dynamodb.Table(TABLE_NAME)


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")

    if raw_body is None:
        raise ValueError("Missing request body")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise ValueError("Request body must be valid JSON")

    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    return payload


def validate_payload(payload: dict[str, Any]) -> tuple[str, str]:
    text = payload.get("text")
    voice = payload.get("voice")

    if not isinstance(text, str):
        raise ValueError("'text' must be a string")

    text = text.strip()

    if not text:
        raise ValueError("'text' cannot be empty")

    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"'text' must not exceed {MAX_TEXT_LENGTH} characters")

    if not isinstance(voice, str):
        raise ValueError("'voice' must be a string")

    voice = voice.strip().lower()

    if voice not in ALLOWED_VOICES:
        raise ValueError("'voice' must be either 'male' or 'female'")

    return text, voice


def build_job_item(user_id: str, job_id: str, text: str, voice: str) -> dict[str, Any]:
    now = int(time.time())

    return {
        "PK": f"USER#{user_id}",
        "SK": f"JOB#{job_id}",
        "jobId": job_id,
        "userId": user_id,
        "status": "PENDING",
        "text": text,
        "voice": voice,
        "createdAt": now,
        "ttl": now + TTL_SECONDS,
    }


def put_job(item: dict[str, Any]) -> None:
    table = get_table()
    table.put_item(Item=item)


def enqueue_job(job_id: str, user_id: str) -> None:
    if not QUEUE_URL:
        raise RuntimeError("QUEUE_URL environment variable is missing")

    message = {
        "jobId": job_id,
        "userId": user_id,
    }

    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message),
    )


def get_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    table = get_table()

    response = table.get_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"JOB#{job_id}",
        },
        ConsistentRead=True,
    )

    return response.get("Item")


def presign(key: str) -> str:
    if not OUTPUT_BUCKET:
        raise RuntimeError("OUTPUT_BUCKET env var missing")

    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": OUTPUT_BUCKET,
            "Key": key,
        },
        ExpiresIn=PRESIGN_EXPIRES,
    )


def handle_create_job(event: dict[str, Any]) -> dict[str, Any]:
    payload = parse_body(event)
    text, voice = validate_payload(payload)

    user_id = DEFAULT_USER_ID
    job_id = str(uuid.uuid4())

    item = build_job_item(user_id, job_id, text, voice)

    put_job(item)
    enqueue_job(job_id, user_id)

    return json_response(
        202,
        {
            "jobId": job_id,
            "status": "PENDING",
        },
    )


def handle_get_job(event: dict[str, Any]) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    job_id = path_params.get("jobId")

    if not job_id:
        return json_response(400, {"error": "Missing jobId"})

    user_id = DEFAULT_USER_ID

    item = get_job(user_id, job_id)

    if not item:
        return json_response(404, {"error": "Job not found"})

    response = {
        "jobId": item.get("jobId"),
        "status": item.get("status"),
        "voice": item.get("voice"),
    }

    if item.get("status") == "DONE":
        audio = item.get("audioKey")
        fr = item.get("subtitleFrKey")
        en = item.get("subtitleEnKey")

        if audio:
            response["audioUrl"] = presign(audio)

        if fr:
            response["subtitleFrUrl"] = presign(fr)

        if en:
            response["subtitleEnUrl"] = presign(en)

    return json_response(200, response)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method")

        if method == "POST":
            return handle_create_job(event)

        if method == "GET":
            return handle_get_job(event)

        return json_response(405, {"error": "Method not allowed"})

    except ValueError as exc:
        return json_response(400, {"error": str(exc)})

    except (ClientError, BotoCoreError) as exc:
        print("AWS error:", exc)
        return json_response(500, {"error": "AWS service error"})

    except Exception as exc:
        print("Unexpected error:", exc)
        return json_response(500, {"error": "Internal server error"})
import json
import os
import re
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


dynamodb = boto3.resource("dynamodb")
polly = boto3.client("polly")
translate = boto3.client("translate")
s3 = boto3.client("s3")

TABLE_NAME = os.getenv("TABLE_NAME")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET")
VOICE_MAPPING = {
    "female": "Celine",
    "male": "Mathieu",
}


def get_table():
    if not TABLE_NAME:
        raise RuntimeError("TABLE_NAME environment variable is missing")
    return dynamodb.Table(TABLE_NAME)


def get_output_bucket() -> str:
    if not OUTPUT_BUCKET:
        raise RuntimeError("OUTPUT_BUCKET environment variable is missing")
    return OUTPUT_BUCKET


def get_job_keys(message: dict[str, Any]) -> tuple[str, str]:
    job_id = message.get("jobId")
    user_id = message.get("userId")

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("SQS message is missing a valid 'jobId'")

    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("SQS message is missing a valid 'userId'")

    return user_id, job_id


def get_job(table, user_id: str, job_id: str) -> dict[str, Any]:
    response = table.get_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"JOB#{job_id}",
        },
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        raise ValueError(f"Job '{job_id}' was not found for user '{user_id}'")
    return item


def update_job_status(table, user_id: str, job_id: str, status: str) -> None:
    now = int(time.time())
    table.update_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"JOB#{job_id}",
        },
        UpdateExpression="SET #status = :status, updatedAt = :updated_at",
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":status": status,
            ":updated_at": now,
        },
    )


def mark_job_done(
    table,
    user_id: str,
    job_id: str,
    audio_key: str,
    subtitle_fr_key: str,
    subtitle_en_key: str,
) -> None:
    now = int(time.time())
    table.update_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"JOB#{job_id}",
        },
        UpdateExpression=(
            "SET #status = :status, "
            "audioKey = :audio_key, "
            "subtitleFrKey = :subtitle_fr_key, "
            "subtitleEnKey = :subtitle_en_key, "
            "updatedAt = :updated_at"
        ),
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":status": "DONE",
            ":audio_key": audio_key,
            ":subtitle_fr_key": subtitle_fr_key,
            ":subtitle_en_key": subtitle_en_key,
            ":updated_at": now,
        },
    )


def mark_job_failed(table, user_id: str, job_id: str, error_message: str) -> None:
    now = int(time.time())
    table.update_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": f"JOB#{job_id}",
        },
        UpdateExpression="SET #status = :status, errorMessage = :error_message, updatedAt = :updated_at",
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":status": "FAILED",
            ":error_message": error_message,
            ":updated_at": now,
        },
    )


def get_voice_id(voice: str) -> str:
    voice_id = VOICE_MAPPING.get(voice)
    if not voice_id:
        raise ValueError(f"Unsupported voice '{voice}'")
    return voice_id


def synthesize_audio(text: str, voice: str) -> bytes:
    response = polly.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId=get_voice_id(voice),
        LanguageCode="fr-FR",
        Engine="standard",
    )

    audio_stream = response.get("AudioStream")
    if audio_stream is None:
        raise RuntimeError("Polly did not return an audio stream")

    return audio_stream.read()


def translate_to_english(text: str) -> str:
    response = translate.translate_text(
        Text=text,
        SourceLanguageCode="fr",
        TargetLanguageCode="en",
    )
    translated_text = response.get("TranslatedText")
    if not isinstance(translated_text, str) or not translated_text.strip():
        raise RuntimeError("Translate did not return a valid translation")
    return translated_text


def split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    segments = re.split(r"(?<=[.!?])\s+", cleaned)
    return [segment.strip() for segment in segments if segment.strip()]


def format_srt_timestamp(total_seconds: float) -> str:
    total_milliseconds = int(total_seconds * 1000)
    hours = total_milliseconds // 3_600_000
    minutes = (total_milliseconds % 3_600_000) // 60_000
    seconds = (total_milliseconds % 60_000) // 1000
    milliseconds = total_milliseconds % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def build_srt(text: str) -> str:
    segments = split_sentences(text)
    if not segments:
        return ""

    lines: list[str] = []
    current_start = 0.0

    for index, segment in enumerate(segments, start=1):
        word_count = len(segment.split())
        duration_seconds = max(2.0, word_count * 0.4)
        end_time = current_start + duration_seconds

        lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(current_start)} --> {format_srt_timestamp(end_time)}",
                segment,
                "",
            ]
        )
        current_start = end_time

    return "\n".join(lines)


def upload_bytes(bucket: str, key: str, content: bytes, content_type: str) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
    )


def process_record(table, output_bucket: str, record: dict[str, Any]) -> None:
    raw_body = record.get("body")
    if raw_body is None:
        raise ValueError("SQS record body is missing")

    try:
        message = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("SQS record body must be valid JSON") from exc

    if not isinstance(message, dict):
        raise ValueError("SQS record body must be a JSON object")

    user_id, job_id = get_job_keys(message)
    job = get_job(table, user_id, job_id)

    text = job.get("text")
    voice = job.get("voice")

    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Job '{job_id}' is missing a valid 'text'")
    if not isinstance(voice, str) or not voice.strip():
        raise ValueError(f"Job '{job_id}' is missing a valid 'voice'")

    print(f"Processing job '{job_id}' for user '{user_id}'")
    update_job_status(table, user_id, job_id, "PROCESSING")

    try:
        audio_bytes = synthesize_audio(text=text, voice=voice)
        translated_text = translate_to_english(text)
        subtitles_fr = build_srt(text)
        subtitles_en = build_srt(translated_text)

        base_key = f"jobs/{job_id}"
        audio_key = f"{base_key}/audio.mp3"
        subtitle_fr_key = f"{base_key}/subtitles_fr.srt"
        subtitle_en_key = f"{base_key}/subtitles_en.srt"

        upload_bytes(output_bucket, audio_key, audio_bytes, "audio/mpeg")
        upload_bytes(output_bucket, subtitle_fr_key, subtitles_fr.encode("utf-8"), "application/x-subrip")
        upload_bytes(output_bucket, subtitle_en_key, subtitles_en.encode("utf-8"), "application/x-subrip")

        mark_job_done(
            table=table,
            user_id=user_id,
            job_id=job_id,
            audio_key=audio_key,
            subtitle_fr_key=subtitle_fr_key,
            subtitle_en_key=subtitle_en_key,
        )
        print(f"Job '{job_id}' completed")

    except Exception as exc:
        error_message = str(exc)
        print(f"Job '{job_id}' failed: {error_message}")
        mark_job_failed(table, user_id, job_id, error_message)
        raise


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    table = get_table()
    output_bucket = get_output_bucket()
    records = event.get("Records", [])

    if not isinstance(records, list) or not records:
        print("No SQS records to process")
        return {"status": "no_records"}

    try:
        for record in records:
            process_record(table, output_bucket, record)

        return {
            "status": "processed",
            "records": len(records),
        }

    except ValueError as exc:
        print(f"Validation error: {exc}")
        raise
    except (ClientError, BotoCoreError) as exc:
        print(f"AWS service error: {exc}")
        raise
    except Exception as exc:
        print(f"Unexpected processor error: {exc}")
        raise
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_apigatewayv2 as apigateway,
    aws_s3 as s3,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration

class MediaAssistantBackendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.jobs_table = dynamodb.Table(
            self, "JobTable",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
        )

        self.output_bucket = s3.Bucket(
            self,
            "MediaOutputBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.jobs_dlq = sqs.Queue(
            self, "JobDLQ",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(14),
        )

        self.jobs_queue = sqs.Queue(
            self, "JobQueue",
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(1),
            dead_letter_queue=sqs.DeadLetterQueue(queue=self.jobs_dlq, max_receive_count=3),
        )

        self.processor_fn = _lambda.Function(
            self, "JobProcessor",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="processor.handler",
            code=_lambda.Code.from_asset("../services/processor/src"),
            environment={
                "TABLE_NAME": self.jobs_table.table_name,
                "QUEUE_URL": self.jobs_queue.queue_url,
                "OUTPUT_BUCKET": self.output_bucket.bucket_name,
            },
            timeout=Duration.minutes(5),
            memory_size=512,
            architecture=_lambda.Architecture.ARM_64,
        )

        logs.LogGroup(
            self,
            "JobProcessorLogGroup",
            log_group_name=f"/aws/lambda/media-assistant-{self.processor_fn.function_name}",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.jobs_table.grant_read_write_data(self.processor_fn)
        self.jobs_queue.grant_consume_messages(self.processor_fn)
        self.output_bucket.grant_put(self.processor_fn)

        self.processor_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["polly:SynthesizeSpeech"],
                resources=["*"],
            )
        )

        self.processor_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["translate:TranslateText"],
                resources=["*"],
            )
        )

        self.processor_fn.add_event_source(
            SqsEventSource(self.jobs_queue)
        )

        self.api_fn = _lambda.Function(
            self, "ApiHandler",
            handler="api.handler",
            code=_lambda.Code.from_asset("../services/api/src"),
            runtime=_lambda.Runtime.PYTHON_3_12,
            timeout=Duration.seconds(30),
            environment={
                "TABLE_NAME": self.jobs_table.table_name,
                "QUEUE_URL": self.jobs_queue.queue_url,
                "OUTPUT_BUCKET": self.output_bucket.bucket_name,
            },
            memory_size=256,
            architecture=_lambda.Architecture.ARM_64,
        )

        logs.LogGroup(
            self,
            "ApiFnLogGroup",
            log_group_name=f"/aws/lambda/media-assistant-{self.api_fn.function_name}",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.jobs_table.grant_read_write_data(self.api_fn)
        self.jobs_queue.grant_send_messages(self.api_fn)
        self.output_bucket.grant_read(self.api_fn)

        self.http_api = apigateway.HttpApi(
            self,
            "JobApi",
            api_name="Job API",
        )

        api_integration = HttpLambdaIntegration(
            "ApiIntegration",
            self.api_fn,
        )

        self.http_api.add_routes(
            path="/jobs",
            methods=[apigateway.HttpMethod.POST],
            integration=api_integration,
        )

        self.http_api.add_routes(
            path="/jobs/{jobId}",
            methods=[apigateway.HttpMethod.GET],
            integration=api_integration,
        )

        CfnOutput(
            self,
            "ApiEndpoint",
            value=self.http_api.api_endpoint
        )

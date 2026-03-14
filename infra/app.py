

import aws_cdk as cdk

from stacks.backend_stack import MediaAssistantBackendStack



app = cdk.App()
MediaAssistantBackendStack(app, "MediaAssistantBackendStack",)

app.synth()

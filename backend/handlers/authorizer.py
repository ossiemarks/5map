"""Lambda authorizer for 5map WebSocket API."""

from typing import Any


def _generate_policy(principal_id: str, effect: str, resource: str) -> dict[str, Any]:
    """Generate an IAM policy document for API Gateway authorization."""
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Authorize WebSocket connections using token validation.

    MVP implementation: accepts any non-empty token.
    Cognito validation will be added in a future iteration.
    """
    token = None

    query_params = event.get("queryStringParameters") or {}
    if query_params.get("token"):
        token = query_params["token"]

    if not token:
        headers = event.get("headers") or {}
        token = headers.get("Authorization") or headers.get("authorization")

    if not token:
        raise Exception("Unauthorized")

    token = token.strip()
    if not token:
        raise Exception("Unauthorized")

    method_arn = event.get("methodArn", "*")

    return _generate_policy("user", "Allow", method_arn)

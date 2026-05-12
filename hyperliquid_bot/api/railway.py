import requests
from config import RAILWAY_TOKEN, RAILWAY_SERVICE_ID, RAILWAY_ENVIRONMENT_ID

RAILWAY_GQL = "https://backboard.railway.app/graphql/v2"

_UPDATE_MUTATION = """
mutation ServiceInstanceUpdate($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
}
"""


def _gql(query: str, variables: dict) -> dict:
    if not RAILWAY_TOKEN:
        raise Exception("RAILWAY_TOKEN не задан")
    if not RAILWAY_SERVICE_ID or not RAILWAY_ENVIRONMENT_ID:
        raise Exception("RAILWAY_SERVICE_ID или RAILWAY_ENVIRONMENT_ID не заданы")
    r = requests.post(
        RAILWAY_GQL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {RAILWAY_TOKEN}", "Content-Type": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise Exception(data["errors"][0]["message"])
    return data.get("data", {})


def stop_service():
    _gql(_UPDATE_MUTATION, {
        "serviceId": RAILWAY_SERVICE_ID,
        "environmentId": RAILWAY_ENVIRONMENT_ID,
        "input": {"numReplicas": 0},
    })


def start_service():
    _gql(_UPDATE_MUTATION, {
        "serviceId": RAILWAY_SERVICE_ID,
        "environmentId": RAILWAY_ENVIRONMENT_ID,
        "input": {"numReplicas": 1},
    })

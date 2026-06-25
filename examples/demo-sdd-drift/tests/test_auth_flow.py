from src.auth_flow import AUTH_FLOW, describe_auth_flow


def test_auth_flow_is_oauth_device_flow():
    assert AUTH_FLOW == "oauth_device_flow"
    assert "OAuth device flow" in describe_auth_flow()

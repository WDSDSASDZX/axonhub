async def test_console_and_assets_are_served_without_exposing_admin_data(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "管理员凭证" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert (await client.get("/assets/app.js")).status_code == 200
    assert (await client.get("/assets/style.css")).status_code == 200
    assert (await client.get("/admin/requests")).status_code == 401


async def test_request_pagination_and_filters(client, admin_headers):
    response = await client.get("/admin/requests?limit=1&status=failed", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}
    assert (await client.get("/admin/requests?limit=101", headers=admin_headers)).status_code == 422

from pathlib import Path


def test_purchase_ui_exposes_a_single_api_submission_refresh_action():
    html = Path("external_systems/ui/index.html").read_text(encoding="utf-8")
    script = Path("external_systems/ui/app.js").read_text(encoding="utf-8")

    assert 'id="refresh-submissions-button"' in html
    assert "async function refreshSubmissions()" in script
    assert "request('/api/submissions')" in script
    assert "refresh-submissions-button" in script


def test_purchase_ui_exposes_purchase_follow_up_form_and_refresh():
    html = Path("external_systems/ui/index.html").read_text(encoding="utf-8")
    script = Path("external_systems/ui/app.js").read_text(encoding="utf-8")

    assert 'id="purchase-follow-up-form"' in html
    assert 'id="follow-up-mes-apply-no"' in html
    assert 'id="follow-up-material"' in html
    assert 'id="follow-up-quantity"' in html
    assert 'id="follow-up-applicant"' in html
    assert 'id="purchase-follow-up-list"' in html
    assert "async function createPurchaseFollowUp(event)" in script
    assert "request('/api/purchase-follow-ups'" in script

"""Saved-model inference and input-boundary tests for the shipping portal."""
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototypes' / 'fraudshield-pipeline'))
import api_portal
from fraudshield.portal_risk import PortalScoreRequest, features_for, saved_model

PAYLOAD = dict(booking_id='PORTAL-TEST', created='2026-10-04T10:00:00+05:30', value=85000,
               quantity=2, category='Electronics', sender_country='India', receiver_country='India', receiver_city='Mumbai')
client = TestClient(api_portal.app)


def test_actual_saved_lightgbm_returns_finite_probability_and_explanation():
    model = saved_model()
    response = client.post('/score', json=PAYLOAD)
    assert response.status_code == 200
    result = response.json()
    assert result['source'] == 'trained'
    assert result['model_version'] == model.model.version
    assert result['booking_id'] == PAYLOAD['booking_id']
    assert 0 <= result['probability'] <= 1
    assert len(result['shap']) == 6
    assert all(np.isfinite(item['value']) for item in result['shap'])
    assert 'is_transfer' in result['missing_features']
    assert any('unknown' in item['name'] for item in result['shap'])
    assert result['probability'] == client.post('/score', json=PAYLOAD).json()['probability']
    assert client.get('/health').json()['status'] == 'ok'


def test_feature_mapping_keeps_unknowns_and_uses_strictly_prior_history():
    request = PortalScoreRequest(**PAYLOAD, history=[
        dict(created='2026-10-02T10:00:00+05:30', value=42500, city='Mumbai', country='India'),
        dict(created=PAYLOAD['created'], value=1, city='Delhi', country='India'),
        dict(created='2026-10-05T10:00:00+05:30', value=1, city='Delhi', country='India'),
    ])
    features = features_for(request, 85)
    assert features['net_total'] == 1000
    assert features['cust_n_prior'] == 1
    assert features['cust_prior_spend'] == 500
    assert features['cust_spend_ratio'] == 2
    assert features['cust_days_since_last'] == 2
    assert features['cust_new_city'] == 0
    assert np.isnan(features['is_transfer'])
    assert np.isnan(features['cust_prior_fraud'])
    assert np.isnan(features['profit_total'])


@pytest.mark.parametrize('patch', [dict(quantity=0), dict(value=-1), dict(created='2026-10-04T10:00:00'), dict(fraud_label=1)])
def test_invalid_or_outcome_inputs_are_rejected(patch):
    assert client.post('/score', json={**PAYLOAD, **patch}).status_code == 422


def test_model_failure_returns_unavailable_without_fallback(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('Model missing')
    monkeypatch.setattr(api_portal, 'score_request', unavailable)
    response = client.post('/score', json=PAYLOAD)
    assert response.status_code == 503
    assert 'probability' not in response.json()


def test_invalid_currency_configuration_returns_unavailable(monkeypatch):
    monkeypatch.setenv('FRAUDSHIELD_DEMO_INR_PER_USD', '0')
    assert client.post('/score', json=PAYLOAD).status_code == 503

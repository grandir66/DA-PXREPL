"""
Test Health and Basic Endpoints
"""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Test basic health and status endpoints"""
    
    def test_health_check(self, client):
        """Test health check endpoint (no auth required)"""
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["auth_enabled"] == True
    
    def test_health_conta_i_job_falliti(self, client):
        """Domarc, 24/11/2026: un job falliva da 50 giorni e /api/health
        diceva solo «healthy». Ora porta il conto, senza cambiare lo stato."""
        data = client.get("/api/health").json()
        assert set(data["jobs"]) == {
            "repliche_fallite", "fallimenti_di_fila_max", "ultima_corsa_riuscita"
        }

    def test_percorso_illeggibile_e_404_non_500(self, client):
        """Domarc, 24/11/2026: uno scanner con byte nulli nel percorso
        produceva 500 con traceback (36 a settimana)."""
        response = client.get("/%00/etc/passwd")
        assert response.status_code == 404

    def test_setup_required(self, client):
        """Test setup required endpoint (no auth required)"""
        response = client.get("/api/setup-required")
        
        assert response.status_code == 200
        assert "setup_required" in response.json()


class TestCORS:
    """Test CORS configuration"""
    
    def test_cors_headers(self, client):
        """Test CORS headers are present"""
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:8420",
                "Access-Control-Request-Method": "GET"
            }
        )
        
        # Should not fail
        assert response.status_code in [200, 405]


class TestErrorHandling:
    """Test error handling"""
    
    def test_404_endpoint(self, client, admin_token):
        """Test 404 for non-existent endpoint"""
        response = client.get(
            "/api/nonexistent",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 404
    
    def test_invalid_json(self, client, admin_token):
        """Test invalid JSON handling"""
        response = client.post(
            "/api/nodes/",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json"
            },
            content="invalid json"
        )
        
        assert response.status_code == 422


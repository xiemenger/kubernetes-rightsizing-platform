import pytest

from app.models.schema import db
from tests.conftest import make_recommendation


class TestMissingJobId:
    def test_returns_400_when_job_id_missing(self, client):
        response = client.get("/api/v1/recommendations")

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "job_id query parameter is required"
        }


class TestInvalidJobId:
    def test_returns_400_for_invalid_uuid(self, client):
        response = client.get("/api/v1/recommendations?job_id=abc")

        assert response.status_code == 400
        assert response.get_json() == {"error": "job_id must be a valid UUID"}


class TestValidJobId:
    def test_returns_matching_recommendations(self, client, sample_job, sample_recommendations):
        response = client.get(f"/api/v1/recommendations?job_id={sample_job.id}")

        assert response.status_code == 200
        body = response.get_json()
        assert body["job_id"] == str(sample_job.id)
        assert body["total_count"] == 2
        assert body["count"] == 2
        assert len(body["recommendations"]) == 2


class TestNamespaceFilter:
    def test_returns_only_matching_namespace(self, client, app, sample_job):
        with app.app_context():
            db.session.add_all(
                [
                    make_recommendation(
                        sample_job.id,
                        namespace="payments",
                        workload_name="checkout-api",
                    ),
                    make_recommendation(
                        sample_job.id,
                        namespace="frontend",
                        workload_name="web-ui",
                    ),
                ]
            )
            db.session.commit()

        response = client.get(
            f"/api/v1/recommendations?job_id={sample_job.id}&namespace=payments"
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["count"] == 1
        assert body["recommendations"][0]["namespace"] == "payments"


class TestMinAggressiveSavingsFilter:
    def test_returns_only_recommendations_above_threshold(self, client, app, sample_job):
        with app.app_context():
            db.session.add_all(
                [
                    make_recommendation(
                        sample_job.id,
                        workload_name="service-a",
                        aggressive_estimated_weekly_savings_usd=50.0,
                    ),
                    make_recommendation(
                        sample_job.id,
                        workload_name="service-b",
                        aggressive_estimated_weekly_savings_usd=200.0,
                    ),
                ]
            )
            db.session.commit()

        response = client.get(
            f"/api/v1/recommendations?job_id={sample_job.id}&min_aggressive_savings=100"
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["count"] == 1
        assert body["recommendations"][0]["workload_name"] == "service-b"
        assert body["recommendations"][0]["aggressive_estimated_weekly_savings_usd"] == 200.0


class TestDefaultSorting:
    def test_sorts_by_aggressive_savings_descending(self, client, app, sample_job):
        with app.app_context():
            db.session.add_all(
                [
                    make_recommendation(
                        sample_job.id,
                        workload_name="low",
                        aggressive_estimated_weekly_savings_usd=50.0,
                    ),
                    make_recommendation(
                        sample_job.id,
                        workload_name="high",
                        aggressive_estimated_weekly_savings_usd=200.0,
                    ),
                    make_recommendation(
                        sample_job.id,
                        workload_name="mid",
                        aggressive_estimated_weekly_savings_usd=100.0,
                    ),
                ]
            )
            db.session.commit()

        response = client.get(f"/api/v1/recommendations?job_id={sample_job.id}")

        assert response.status_code == 200
        savings = [
            rec["aggressive_estimated_weekly_savings_usd"]
            for rec in response.get_json()["recommendations"]
        ]
        assert savings == [200.0, 100.0, 50.0]


class TestPagination:
    def test_returns_requested_page(self, client, app, sample_job):
        with app.app_context():
            rows = [
                make_recommendation(
                    sample_job.id,
                    workload_name=f"service-{index}",
                    aggressive_estimated_weekly_savings_usd=float(index),
                )
                for index in range(25)
            ]
            db.session.add_all(rows)
            db.session.commit()

        response = client.get(
            f"/api/v1/recommendations?job_id={sample_job.id}&page=2&page_size=10"
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["page"] == 2
        assert body["page_size"] == 10
        assert body["total_count"] == 25
        assert body["count"] == 10


class TestInvalidPagination:
    @pytest.mark.parametrize(
        "query",
        [
            "page=0",
            "page_size=0",
            "page_size=500",
        ],
    )
    def test_returns_400_for_invalid_pagination(self, client, sample_job, query):
        response = client.get(
            f"/api/v1/recommendations?job_id={sample_job.id}&{query}"
        )

        assert response.status_code == 400
        assert "error" in response.get_json()

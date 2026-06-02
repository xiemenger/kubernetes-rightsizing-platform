import uuid
from typing import Optional, Tuple

from flask import Blueprint, jsonify, request

from app.models.schema import Recommendation

recommendations_bp = Blueprint(
    "recommendations", __name__, url_prefix="/api/v1/recommendations"
)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _parse_page_param(
    value: Optional[str],
    default: int,
    name: str,
    max_value: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """Parse and validate a positive integer query parameter."""
    if value is None:
        return default, None

    try:
        parsed = int(value)
    except ValueError:
        return None, f"{name} must be an integer"

    if parsed < 1:
        return None, f"{name} must be >= 1"

    if max_value is not None and parsed > max_value:
        return None, f"{name} must be <= {max_value}"

    return parsed, None


@recommendations_bp.route("", methods=["GET"])
def list_recommendations():
    """
    GET /api/v1/recommendations?job_id=<uuid>&namespace=<ns>&min_aggressive_savings=<usd>
    Returns persisted rightsizing recommendations for a completed job.
    """
    job_id = request.args.get("job_id")
    if not job_id:
        return jsonify({"error": "job_id query parameter is required"}), 400

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return jsonify({"error": "job_id must be a valid UUID"}), 400

    page, page_error = _parse_page_param(request.args.get("page"), DEFAULT_PAGE, "page")
    if page_error:
        return jsonify({"error": page_error}), 400

    page_size, page_size_error = _parse_page_param(
        request.args.get("page_size"),
        DEFAULT_PAGE_SIZE,
        "page_size",
        max_value=MAX_PAGE_SIZE,
    )
    if page_size_error:
        return jsonify({"error": page_size_error}), 400

    query = Recommendation.query.filter_by(job_id=job_uuid)

    namespace = request.args.get("namespace")
    if namespace:
        query = query.filter(Recommendation.namespace == namespace)

    min_aggressive_savings = request.args.get("min_aggressive_savings")
    if min_aggressive_savings is not None:
        try:
            min_savings = float(min_aggressive_savings)
        except ValueError:
            return jsonify({"error": "min_aggressive_savings must be a number"}), 400
        query = query.filter(
            Recommendation.aggressive_estimated_weekly_savings_usd >= min_savings
        )

    # Highest savings first — surfaces the most actionable opportunities at the top.
    query = query.order_by(
        Recommendation.aggressive_estimated_weekly_savings_usd.desc()
    )

    # Pagination avoids loading large result sets into memory at once.
    total_count = query.count()
    offset = (page - 1) * page_size
    recommendations = query.offset(offset).limit(page_size).all()

    return jsonify(
        {
            "job_id": str(job_uuid),
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "count": len(recommendations),
            "recommendations": [rec.to_dict() for rec in recommendations],
        }
    ), 200

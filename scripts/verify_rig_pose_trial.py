"""Verify the trial Capture through the running authenticated API."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid

from progress_api.db import SessionLocal
from progress_api.models import ProjectMember
from progress_api.security import create_access_token
from sqlalchemy import select


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()

    with SessionLocal() as db:
        user_id = db.scalar(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == args.project_id
            )
        )
    if user_id is None:
        raise RuntimeError("Project has no member for authenticated verification")
    token, _expires_in = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}
    detail_url = f"{args.api}/projects/{args.project_id}/captures/{args.capture_id}"
    request = urllib.request.Request(detail_url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        detail = json.load(response)
        status = response.status
    stations = [frame for frame in detail["keyframes"] if frame["is_warp_point"]]
    first_image = (
        f"{detail_url}/keyframes/{stations[0]['id']}/image"
        if stations
        else None
    )
    image_status = None
    image_redirect = None
    if first_image:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(
                urllib.request.Request(first_image, headers=headers), timeout=30
            ) as response:
                image_status = response.status
        except urllib.error.HTTPError as error:
            image_status = error.code
            image_redirect = error.headers.get("Location")
    algorithms = sorted(
        {
            frame["pose"]["algorithm"]
            for frame in detail["keyframes"]
            if frame.get("pose")
        }
    )
    print(
        json.dumps(
            {
                "detail_status": status,
                "image_status": image_status,
                "image_redirect_present": bool(image_redirect),
                "keyframes": len(detail["keyframes"]),
                "warp_points": len(stations),
                "route_vectors": len(detail["route_vectors"]),
                "first_station_ms": stations[0]["timestamp_ms"] if stations else None,
                "last_station_ms": stations[-1]["timestamp_ms"] if stations else None,
                "algorithms": algorithms,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

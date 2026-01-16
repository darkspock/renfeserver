"""Network metadata API endpoints."""
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from src.gtfs_bc.network.infrastructure.models import NetworkModel
from src.gtfs_bc.route.infrastructure.models import RouteModel


router = APIRouter(prefix="/gtfs/networks", tags=["networks"])


def natural_sort_key(line_code: str) -> tuple:
    """
    Natural sort key for line codes like C1, C2, C10, C4a, C4b.
    Returns tuple for proper sorting: ('C', 1, '') for C1, ('C', 4, 'a') for C4a.
    """
    match = re.match(r'([A-Za-z]+)(\d+)([a-z]*)', line_code)
    if match:
        prefix, number, suffix = match.groups()
        return (prefix, int(number), suffix)
    return (line_code, 0, '')


class NetworkResponse(BaseModel):
    """Response model for network."""

    code: str
    name: str
    city: str
    region: str
    color: str
    text_color: str
    logo_url: Optional[str] = None
    wikipedia_url: Optional[str] = None
    description: Optional[str] = None
    route_count: int = 0

    class Config:
        from_attributes = True


class LineResponse(BaseModel):
    """Response model for a line within a network."""

    line_code: str  # e.g., "C1", "C2"
    color: str
    text_color: str
    route_count: int
    routes: List[dict]


class NetworkDetailResponse(NetworkResponse):
    """Detailed network response with lines."""

    lines: List[LineResponse] = []


@router.get("", response_model=List[NetworkResponse])
async def get_networks(db: Session = Depends(get_db)):
    """Get all Cercanías networks with route counts."""
    networks = db.query(NetworkModel).all()

    results = []
    for network in networks:
        # Count routes for this network
        route_count = (
            db.query(RouteModel)
            .filter(RouteModel.id.like(f"{network.code}%"))
            .count()
        )

        results.append(
            NetworkResponse(
                code=network.code,
                name=network.name,
                city=network.city,
                region=network.region,
                color=network.color,
                text_color=network.text_color,
                logo_url=network.logo_url,
                wikipedia_url=network.wikipedia_url,
                description=network.description,
                route_count=route_count,
            )
        )

    return results


@router.get("/{code}", response_model=NetworkDetailResponse)
async def get_network(code: str, db: Session = Depends(get_db)):
    """Get network details with all lines and their colors."""
    network = db.query(NetworkModel).filter(NetworkModel.code == code).first()

    if not network:
        raise HTTPException(status_code=404, detail=f"Network {code} not found")

    # Get all routes for this network
    routes = (
        db.query(RouteModel)
        .filter(RouteModel.id.like(f"{code}%"))
        .order_by(RouteModel.short_name)
        .all()
    )

    # Group routes by line code
    lines_dict = {}
    for route in routes:
        line_code = route.short_name
        if line_code not in lines_dict:
            lines_dict[line_code] = {
                "line_code": line_code,
                "color": route.color or network.color,
                "text_color": route.text_color or network.text_color,
                "routes": [],
            }
        lines_dict[line_code]["routes"].append(
            {
                "id": route.id,
                "long_name": route.long_name,
                "color": route.color,
            }
        )

    # Convert to list with natural sort
    lines = sorted(
        [
            LineResponse(
                line_code=data["line_code"],
                color=data["color"],
                text_color=data["text_color"],
                route_count=len(data["routes"]),
                routes=data["routes"],
            )
            for data in lines_dict.values()
        ],
        key=lambda x: natural_sort_key(x.line_code)
    )

    return NetworkDetailResponse(
        code=network.code,
        name=network.name,
        city=network.city,
        region=network.region,
        color=network.color,
        text_color=network.text_color,
        logo_url=network.logo_url,
        wikipedia_url=network.wikipedia_url,
        description=network.description,
        route_count=len(routes),
        lines=lines,
    )


@router.get("/{code}/lines", response_model=List[LineResponse])
async def get_network_lines(code: str, db: Session = Depends(get_db)):
    """Get all lines for a network with their colors."""
    network = db.query(NetworkModel).filter(NetworkModel.code == code).first()

    if not network:
        raise HTTPException(status_code=404, detail=f"Network {code} not found")

    # Get all routes for this network
    routes = (
        db.query(RouteModel)
        .filter(RouteModel.id.like(f"{code}%"))
        .order_by(RouteModel.short_name)
        .all()
    )

    # Group routes by line code
    lines_dict = {}
    for route in routes:
        line_code = route.short_name
        if line_code not in lines_dict:
            lines_dict[line_code] = {
                "line_code": line_code,
                "color": route.color or network.color,
                "text_color": route.text_color or network.text_color,
                "routes": [],
            }
        lines_dict[line_code]["routes"].append(
            {
                "id": route.id,
                "long_name": route.long_name,
                "color": route.color,
            }
        )

    return sorted(
        [
            LineResponse(
                line_code=data["line_code"],
                color=data["color"],
                text_color=data["text_color"],
                route_count=len(data["routes"]),
                routes=data["routes"],
            )
            for data in lines_dict.values()
        ],
        key=lambda x: natural_sort_key(x.line_code)
    )

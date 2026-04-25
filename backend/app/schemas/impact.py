"""Pydantic schemas for Impact Summary responses."""

from pydantic import BaseModel, Field


class InfrastructureAtRisk(BaseModel):
    """Summary of one type of infrastructure at risk."""

    type: str = Field(..., examples=["hospital"])
    count: int = Field(..., examples=[3])
    names: list[str] = Field(
        default_factory=list,
        examples=[["Spitalul Județean", "Spitalul de Urgență"]],
    )


class RegionImpact(BaseModel):
    """Impact summary for a single NUTS region."""

    nuts_id: str = Field(..., examples=["RO224"])
    region_name: str = Field(..., examples=["Județul Galați"])
    risk_score: float = Field(..., examples=[91.2])
    hazard_type: str = Field(..., examples=["fluvial"])
    affected_population: int = Field(default=0, examples=[12000])
    infrastructure_at_risk: list[InfrastructureAtRisk] = []
    alert_level: str = Field(
        ...,
        examples=["emergency"],
        description="Derived: info / warning / critical / emergency",
    )
    summary_text: str = Field(
        ...,
        examples=[
            "Risc Critic în RO224 (Galați). Infrastructură la risc: "
            "Spitalul Județean, 3 școli, stație de transformare."
        ],
    )


class ImpactSummaryResponse(BaseModel):
    """Overall impact summary across all monitored regions."""

    total_regions_at_risk: int = Field(default=0)
    total_affected_population: int = Field(default=0)
    total_hospitals_at_risk: int = Field(default=0)
    total_schools_at_risk: int = Field(default=0)
    regions: list[RegionImpact] = []

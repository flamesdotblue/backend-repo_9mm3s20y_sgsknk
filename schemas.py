from pydantic import BaseModel, Field, conlist
from typing import Optional, List, Literal

# Performance Management System Schemas

Category = Literal['Increase', 'Decrease', 'Control']
AggregationMethod = Literal['Sum', 'Average']
Frequency = Literal['Daily', 'Weekly', 'Fortnightly', 'Monthly']

class Kpi(BaseModel):
    name: str = Field(..., description="KPI Name")
    unit: str = Field(..., description="Unit of Measure, e.g., %, $, units")
    category: Category = Field(..., description="How performance is measured")
    weightage: float = Field(..., gt=0, description="Weightage as number e.g., 20 for 20%")
    start_value: float = Field(..., description="Start value representing 0% baseline")
    target_value: float = Field(..., description="Target value representing 100% goal")
    aggregation: AggregationMethod = Field(..., description="Aggregation method for sub-period values")
    frequency: Frequency = Field(..., description="Tracking frequency")

class KpiData(BaseModel):
    kpi_id: str = Field(..., description="Associated KPI id")
    # values will depend on frequency; keep generic list
    values: conlist(float, min_length=1) = Field(..., description="Sub-period values in order")
    actual: Optional[float] = Field(None, description="Computed actual value")
    percentage: Optional[float] = Field(None, description="Computed percentage 0-100")

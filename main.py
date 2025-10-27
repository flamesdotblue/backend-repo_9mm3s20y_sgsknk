import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone

from database import db, create_document, get_documents
from schemas import Kpi, KpiData

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


def compute_actual(values: List[float], aggregation: str) -> float:
    if not values:
        return 0.0
    if aggregation == 'Sum':
        return float(sum(values))
    # Average
    return float(sum(values) / len(values))


def clamp_percentage(p: float) -> float:
    return max(0.0, min(100.0, p))


def compute_percentage(category: str, actual: float, start: float, target: float) -> float:
    # Avoid division by zero
    if category in ['Increase', 'Decrease'] and start == target:
        return 0.0
    if category == 'Increase':
        pct = ((actual - start) / (target - start)) * 100.0
    elif category == 'Decrease':
        pct = ((start - actual) / (start - target)) * 100.0
    else:  # Control
        pct = 100.0 if (actual >= start and actual <= target) or (target >= start and start <= actual <= target) else 0.0
        # The above handles general case; simplify to inside range yields 100
        pct = 100.0 if start <= actual <= target or target <= actual <= start else 0.0
    return clamp_percentage(float(pct))


@app.get("/")
def read_root():
    return {"message": "PMS Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# KPI Endpoints
@app.post("/api/kpis")
def create_kpi(kpi: Kpi):
    kpi_dict = kpi.model_dump()
    kpi_dict['created_at'] = datetime.now(timezone.utc)
    kpi_dict['updated_at'] = datetime.now(timezone.utc)
    inserted_id = db['kpi'].insert_one(kpi_dict).inserted_id
    return {"id": str(inserted_id), **kpi_dict}


@app.get("/api/kpis")
def list_kpis():
    items = list(db['kpi'].find())
    result = []
    for it in items:
        kid = str(it.get('_id'))
        data = db['kpi_data'].find_one({"kpi_id": kid})
        result.append({
            "id": kid,
            "name": it.get('name'),
            "unit": it.get('unit'),
            "category": it.get('category'),
            "weightage": it.get('weightage'),
            "start_value": it.get('start_value'),
            "target_value": it.get('target_value'),
            "aggregation": it.get('aggregation'),
            "frequency": it.get('frequency'),
            "data": {
                "values": data.get('values') if data else None,
                "actual": data.get('actual') if data else None,
                "percentage": data.get('percentage') if data else None,
                "updated_at": data.get('updated_at') if data else None,
            }
        })
    return result


@app.get("/api/kpis/{kpi_id}")
def get_kpi(kpi_id: str):
    doc = db['kpi'].find_one({"_id": oid(kpi_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="KPI not found")
    data = db['kpi_data'].find_one({"kpi_id": kpi_id})
    return {
        "id": kpi_id,
        **{k: doc.get(k) for k in ["name","unit","category","weightage","start_value","target_value","aggregation","frequency"]},
        "data": data
    }


@app.put("/api/kpis/{kpi_id}")
def update_kpi(kpi_id: str, kpi: Kpi):
    res = db['kpi'].update_one({"_id": oid(kpi_id)}, {"$set": {**kpi.model_dump(), "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="KPI not found")
    return {"id": kpi_id, **kpi.model_dump()}


@app.post("/api/kpis/{kpi_id}/data")
def save_kpi_data(kpi_id: str, payload: KpiData):
    # Validate KPI exists
    doc = db['kpi'].find_one({"_id": oid(kpi_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="KPI not found")
    values = [float(v) for v in payload.values]
    actual = compute_actual(values, doc.get('aggregation'))
    percentage = compute_percentage(doc.get('category'), actual, float(doc.get('start_value')), float(doc.get('target_value')))
    record = {
        "kpi_id": kpi_id,
        "values": values,
        "actual": actual,
        "percentage": percentage,
        "updated_at": datetime.now(timezone.utc)
    }
    # Upsert per KPI
    db['kpi_data'].update_one({"kpi_id": kpi_id}, {"$set": record}, upsert=True)
    return record


@app.get("/api/weighted-score")
def weighted_score():
    # Join kpi + kpi_data, compute weighted average
    kpis = list(db['kpi'].find())
    total_weight = 0.0
    weighted_sum = 0.0
    for k in kpis:
        kid = str(k.get('_id'))
        data = db['kpi_data'].find_one({"kpi_id": kid})
        if not data or data.get('percentage') is None:
            continue
        w = float(k.get('weightage', 0) or 0)
        if w <= 0:
            continue
        total_weight += w
        weighted_sum += float(data.get('percentage')) * w
    if total_weight <= 0:
        return {"weighted_score": None, "display": "N/A"}
    score = weighted_sum / total_weight
    return {"weighted_score": score, "display": f"{score:.2f}%"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

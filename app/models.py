"""Modelos ORM: cache persistente e histórico de séries temporais."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class CacheEntry(Base):
    """Resposta de API armazenada com expiração, sobrevive a reinícios."""

    __tablename__ = "cache"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    fetched_at: Mapped[float] = mapped_column(Float)

    def decode(self) -> Any:
        return json.loads(self.payload)

    @property
    def is_fresh(self) -> bool:
        return time.time() < self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.fetched_at


class MetricPoint(Base):
    """Um ponto de série temporal, usado nos gráficos históricos."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("ix_series_time", "series", "recorded_at"),)

    def as_dict(self) -> dict[str, Any]:
        return {
            "series": self.series,
            "value": self.value,
            "t": self.recorded_at,
            "iso": datetime.fromtimestamp(self.recorded_at, timezone.utc).isoformat(),
        }


class EventLog(Base):
    """Trilha de auditoria exibida no painel de atividade ao vivo."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, index=True)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "t": self.created_at,
        }


_engine = create_engine(settings.database_url, future=True, echo=False)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return SessionLocal()


# --- Helpers de alto nível -------------------------------------------------

def record_metric(series: str, value: float, *, session: Session | None = None) -> None:
    own = session is None
    s = session or get_session()
    try:
        s.add(MetricPoint(series=series, value=float(value), recorded_at=time.time()))
        if own:
            s.commit()
    finally:
        if own:
            s.close()


def history(series: str, limit: int = 120) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.scalars(
            select(MetricPoint)
            .where(MetricPoint.series == series)
            .order_by(MetricPoint.recorded_at.desc())
            .limit(limit)
        ).all()
    return [r.as_dict() for r in reversed(rows)]


def log_event(level: str, source: str, message: str) -> dict[str, Any]:
    with get_session() as s:
        ev = EventLog(
            level=level, source=source, message=message, created_at=time.time()
        )
        s.add(ev)
        s.commit()
        return ev.as_dict()


def recent_events(limit: int = 40) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.scalars(
            select(EventLog).order_by(EventLog.created_at.desc()).limit(limit)
        ).all()
    return [r.as_dict() for r in rows]


def prune(max_age_seconds: int = 60 * 60 * 48) -> int:
    """Remove métricas/eventos antigos e cache expirado. Retorna linhas apagadas."""
    cutoff = time.time() - max_age_seconds
    with get_session() as s:
        n = s.execute(delete(MetricPoint).where(MetricPoint.recorded_at < cutoff)).rowcount
        n += s.execute(delete(EventLog).where(EventLog.created_at < cutoff)).rowcount
        n += s.execute(delete(CacheEntry).where(CacheEntry.expires_at < time.time())).rowcount
        s.commit()
    return n or 0

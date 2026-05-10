from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from services.common.database import Base, TimeStampMixin


class PipelineType(Base, TimeStampMixin):
    __tablename__ = "pipeline_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    base_cost = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", name="uq_pipeline_types_name"),
        CheckConstraint(
            "base_cost >= 0", name="ck_pipeline_types_base_cost_nonneg"
        ),
    )


class TokenTransaction(Base):
    """Append-only wallet ledger. Balance = SUM(delta) per owner."""

    __tablename__ = "token_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    anon_id = Column(UUID(as_uuid=True), nullable=True)
    pipeline_id = Column(UUID(as_uuid=True), nullable=True)
    pipeline_type_id = Column(
        Integer, ForeignKey("pipeline_types.id"), nullable=True
    )
    delta = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR anon_id IS NOT NULL",
            name="ck_token_transactions_owner",
        ),
        CheckConstraint(
            "reason IN ('signup_grant','anon_grant','charge','refund','anon_migration')",
            name="ck_token_transactions_reason",
        ),
    )

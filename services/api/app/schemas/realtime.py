"""Realtime contracts: the WebSocket ticket and encouragement reactions."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import StrictModel

# A small, fixed set of encouragement reactions — never free-form text over the socket.
ReactionEmoji = Literal["clap", "fire", "muscle", "sparkles", "heart"]


class TicketResponse(BaseModel):
    ticket: str
    expires_in: int


class ReactionRequest(StrictModel):
    target_id: uuid.UUID
    emoji: ReactionEmoji

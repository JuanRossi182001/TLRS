from pydantic import BaseModel


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int


class StoredWebSocketTicket(BaseModel):
    user_id: int
    session_id: int


class RealtimeConnectionScope(BaseModel):
    user_id: int
    session_id: int
    client_id: int
    is_admin: bool = False

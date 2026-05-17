# Project Engineering Preferences

This project should be designed with production-readiness in mind.

Prefer decisions that avoid near-term rewrites while keeping the codebase understandable. The app does not need hyperscale architecture, but it should handle meaningful production load.

Default preferences:
- Favor scalable patterns over quick prototypes when the cost is reasonable.
- Keep business logic out of routers; use service/application layers.
- Design database access, authentication, authorization, and realtime flows so they can grow without major rewrites.
- For realtime features, prefer event-driven boundaries over tight coupling.
- Avoid premature complexity, but do not choose approaches that are likely to force a full refactor soon.
- When choosing between sync and async architecture, consider future WebSocket/realtime load and database concurrency, not only the immediate endpoint.
- Explain tradeoffs when a simpler choice may become limiting later.

Realtime/location tracking is a core product concern. Design telemetry and WebSocket flows with production use in mind: clear event boundaries, authorization checks, and a path to multi-instance support.

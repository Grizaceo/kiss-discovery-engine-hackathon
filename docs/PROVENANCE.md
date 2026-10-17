# Provenance
Created 2026-10-17T16:26:36.417691-03:00 (real local timestamp).

## Preparatory design, not product code
Sources: local preparation workspace (`~/.hermes/...`, not included) documents 04, 09-lecciones-de-uso, 10, 09-setup-verificado, 11 and official vendor documentation. These contain earlier designs and experiments (including October 15); they are not presented as new implementation. The full preparation directory is not copied.

## Event implementation
New repository created 2026-10-17T16:26:10-03:00 from an empty directory after Cristóbal explicitly confirmed organizer approval to begin before the scheduled 16:30 build. Code, adapters, harness and tests are newly written during this event. No old KISS implementation repository or preparatory smoke code is imported or copied. Fixture solutions must be labeled tests; only real API responses are attributed to Mercury.

## External dependencies and references
Python, uv, createos-sandbox (official Python SDK, MIT), httpx, python-dotenv, pytest, Ruff, hatchling. Exact versions will be recorded in uv.lock. CreateOS docs: Concepts, SDK Overview, REST Pause-Resume-Fork, Egress, Networks. Stripe Projects installed CLI v0.50.0 links the existing provisioned stack. Mercury uses direct Inception API.

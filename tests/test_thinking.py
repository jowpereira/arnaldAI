"""Testes para ThinkingEmitter — feedback mid-run."""

from __future__ import annotations

from arnaldo.kernel.thinking import ThinkingEmitter, ThinkingEvent, ThinkingKind


class TestThinkingEmitterNoListeners:
    def test_emit_without_callbacks_noop(self) -> None:
        emitter = ThinkingEmitter()
        event = ThinkingEvent(kind=ThinkingKind.SEARCHING, message="test")
        # Não deve crashar
        emitter.emit(event)
        assert not emitter.has_listeners

    def test_searching_shortcut_without_callbacks(self) -> None:
        emitter = ThinkingEmitter()
        emitter.searching("query test")  # noop


class TestThinkingEmitterEmits:
    def test_callback_receives_event(self) -> None:
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)
        assert emitter.has_listeners

        emitter.emit(ThinkingEvent(kind=ThinkingKind.ANALYZING, message="x"))
        assert len(received) == 1
        assert received[0].kind == ThinkingKind.ANALYZING
        assert received[0].message == "x"

    def test_multiple_callbacks(self) -> None:
        emitter = ThinkingEmitter()
        a: list[ThinkingEvent] = []
        b: list[ThinkingEvent] = []
        emitter.register(a.append)
        emitter.register(b.append)

        emitter.searching("q")
        assert len(a) == 1
        assert len(b) == 1


class TestThinkingEmitterSearchingShortcut:
    def test_searching_emits_searching_kind(self) -> None:
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)

        emitter.searching("azure openai", source="web")
        assert len(received) == 1
        assert received[0].kind == ThinkingKind.SEARCHING
        assert "azure openai" in received[0].message
        assert received[0].query == "azure openai"
        assert received[0].metadata == {"source": "web"}

    def test_analyzing_emits_analyzing_kind(self) -> None:
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)

        emitter.analyzing("ambiguidade detectada")
        assert received[0].kind == ThinkingKind.ANALYZING

    def test_resolving_emits_resolving_kind(self) -> None:
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)

        emitter.resolving("contradição X")
        assert received[0].kind == ThinkingKind.RESOLVING


class TestThinkingEmitterErrorHandling:
    def test_callback_error_does_not_crash(self) -> None:
        emitter = ThinkingEmitter()
        good: list[ThinkingEvent] = []

        def bad_callback(event: ThinkingEvent) -> None:
            raise ValueError("boom")

        emitter.register(bad_callback)
        emitter.register(good.append)

        # Não crashar, e segundo callback recebe evento
        emitter.searching("test")
        assert len(good) == 1


class TestThinkingEmitterReset:
    def test_reset_clears_callbacks(self) -> None:
        emitter = ThinkingEmitter()
        received: list[ThinkingEvent] = []
        emitter.register(received.append)
        emitter.reset()
        emitter.searching("q")
        assert received == []

    def test_reset_allows_re_register(self) -> None:
        emitter = ThinkingEmitter()
        first: list[ThinkingEvent] = []
        second: list[ThinkingEvent] = []
        emitter.register(first.append)
        emitter.reset()
        emitter.register(second.append)
        emitter.searching("q")
        assert first == []
        assert len(second) == 1

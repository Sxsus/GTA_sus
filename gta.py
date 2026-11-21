"""
gta.py — Moduł ulepszający rozgrywkę, naprawiający błędy stanu oraz integrujący
asystenta Groq AI dla gry GTA SUS 3D: Infinity Edition.

Uruchomienie:
  python gta.py                  # generuje gameplay_tuning.js i uruchamia lokalny serwer API (port 8765)
  python gta.py --self-test      # uruchamia szybki test modułu
  python gta.py --no-server      # tylko generuje gameplay_tuning.js
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

DEFAULT_GROQ_KEYS: list[str] = [
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
]


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if num != num or num in (float("inf"), float("-inf")):
        return default
    return max(low, min(high, num))


class StateSanitizer:
    """Naprawia nieprawidłowe lub niespójne wartości stanu gry przesyłane z klienta."""

    @staticmethod
    def repair_state(raw_state: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        state = dict(raw_state or {})
        fixes: list[str] = []

        # 1. HP gracza
        raw_hp = state.get("hp", 100)
        fixed_hp = int(round(_clamp(raw_hp, 0, 100, 100)))
        if fixed_hp != raw_hp:
            fixes.append(f"Skorygowano HP ({raw_hp} -> {fixed_hp}).")
        state["hp"] = fixed_hp

        # 2. Gotówka (nie może być ujemna ani NaN)
        raw_cash = state.get("cash", 1000)
        fixed_cash = int(round(_clamp(raw_cash, 0, 10_000_000_000, 1000)))
        if fixed_cash != raw_cash:
            fixes.append(f"Naprawiono stan gotówki (${raw_cash} -> ${fixed_cash}).")
        state["cash"] = fixed_cash

        # 3. Poziom pościgu 0..6
        raw_stars = state.get("stars", 0)
        fixed_stars = int(round(_clamp(raw_stars, 0, 6, 0)))
        if fixed_stars != raw_stars:
            fixes.append(f"Ujednolicono poziom pościgu ({raw_stars} -> {fixed_stars}★).")
        state["stars"] = fixed_stars

        # 4. Wysokość i bezpieczne awaryjne otwarcie spadochronu
        altitude = _clamp(state.get("altitude", 0.0), -50.0, 5000.0, 0.0)
        vy = _clamp(state.get("vy", 0.0), -250.0, 250.0, 0.0)
        in_vehicle = bool(state.get("inVehicle", False))
        parachute_open = bool(state.get("parachuteOpen", False))
        has_parachute = bool(state.get("hasParachute", True))

        if not in_vehicle and altitude > 14.0 and vy < -14.0 and not parachute_open:
            if has_parachute:
                parachute_open = True
                fixes.append("Awaryjnie otwarto spadochron przy dużym spadku.")
            else:
                fixes.append("Ostrzeżenie: spadek z wysokości bez spadochronu — grozi obrażenie od upadku.")

        # 5. Blokada wjazdu zwykłych aut do głębokiej wody
        vehicle_type = str(state.get("vehicleType", "car")).lower()
        in_water = bool(state.get("inWater", False))
        block_car_in_water = False
        if in_vehicle and in_water and vehicle_type not in ("boat", "ship", "jet_ski"):
            block_car_in_water = True
            fixes.append("Zablokowano wjazd pojazdu lądowego do głębokiej wody (użyj łodzi lub mostu).")

        state["altitude"] = round(altitude, 2)
        state["vy"] = round(vy, 2)
        state["inVehicle"] = in_vehicle
        state["parachuteOpen"] = parachute_open
        state["blockCarInWater"] = block_car_in_water
        state["onMoon"] = bool(state.get("onMoon", False))
        return state, fixes


class GameplayBalancer:
    """Silnik ulepszający parametry rozgrywki, fizykę, ekonomię oraz podpowiedzi."""

    def __init__(self, seed: str = "DUBAI-SUS-64", wanted_level: int = 1, cash: int = 1000) -> None:
        self.seed = str(seed or "DUBAI-SUS-64")
        self.wanted_level = int(_clamp(wanted_level, 0, 6, 1))
        self.cash = int(_clamp(cash, 0, 10_000_000_000, 1000))

    def _seed_factor(self, salt: str = "") -> float:
        digest = hashlib.sha256(f"{self.seed}:{salt}".encode("utf-8")).hexdigest()
        val = int(digest[:8], 16) / 0xFFFFFFFF
        return round(0.88 + val * 0.28, 3)

    def build_tuning_profile(self) -> dict[str, Any]:
        chaos_mult = self._seed_factor("chaos")
        loot_mult = self._seed_factor("loot")

        return {
            "version": "10.64-gta-py",
            "seed": self.seed,
            "economy": {
                "startingCash": 1000,
                "shopItemPrice": 100,
                "shopHeistPayout": int(round(900 * loot_mult)),
                "bankHeistPayout": int(round(7000 * loot_mult)),
                "supplyDropBonus": int(round(550 * loot_mult)),
                "cashPerStarRiskBonus": 300 * self.wanted_level,
            },
            "vehiclesAndFlight": {
                "garageTotalVehicles": 400,
                "uniqueModelsCount": 54,
                "lamborghiniFleetBoostTopSpeed": 1.18,
                "nitroSpeedMultiplier": 1.7,
                "waterCollisionBlockForCars": True,
                "boatBuoyancyGain": 1.3,
                "spacebarClimbLift": {
                    "airplaneClimbRate": 27.5,
                    "airplanePitchResponse": 1.4,
                    "helicopterLiftAccel": 33.5,
                    "helicopterHoverStabilizer": 0.94,
                    "descendKeyRate": 18.5,
                    "minSafeAltitude": 1.2,
                },
            },
            "fallAndParachute": {
                "fallDamageThresholdHeight": 11.5,
                "fallDamageMultiplier": 3.2,
                "parachuteAutoDeploySafe": True,
                "parachuteDescentSpeed": 5.0,
                "parachuteGlideForwardBoost": 1.3,
            },
            "nasaMoonMission": {
                "launchDurationSec": 5.2,
                "returnDurationSec": 4.8,
                "moonGravityScale": 0.24,
                "moonJumpImpulse": 15.0,
                "moonExplorationReward": int(round(2750 * loot_mult)),
            },
            "wantedAndNpcs": {
                "wantedLevel": self.wanted_level,
                "policeSpawnRadius": max(55, 130 - self.wanted_level * 12),
                "tankAggroStartsAtStars": 4,
                "npcRagdollImpulseScale": round(1.25 * chaos_mult, 2),
            },
        }

    def advise_player(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        repaired, fixes = StateSanitizer.repair_state(context)
        cash = repaired["cash"]
        hp = repaired["hp"]
        stars = repaired["stars"]
        in_vehicle = repaired["inVehicle"]
        vehicle_type = str((context or {}).get("vehicleType", "car")).lower()
        on_moon = repaired["onMoon"]
        has_parachute = bool((context or {}).get("hasParachute", True))

        suggestions: list[str] = []
        if on_moon:
            priority_action = "Eksploruj powierzchnię Księżyca w niskiej grawitacji, a potem użyj [E] przy rakiecie, aby wrócić na Ziemię."
            suggestions.append("Sprawdź widoki na orbitę i skacz wysoko dzięki niskiej grawitacji.")
            suggestions.append("Po powrocie na Ziemię przetestuj lot samolotem na Spacji nad wieżowcami.")
        elif hp < 40:
            priority_action = "Niski poziom HP — zjedz coś lub weź apteczkę w sklepie ($100) albo wezwij zrzut [G]."
            suggestions.append("Otwieraj spadochron ([Spacja] w powietrzu lub [O]) przed lądowaniem z dużej wysokości.")
        elif stars >= 4:
            priority_action = "Pościg 4–6★ — uważaj na czołg i użyj nitro [N], przejeżdżając przez mosty lub wpadając do budynku [E]."
            suggestions.append("Nie wjeżdżaj zwykłym autem do głębokiej wody — wybierz łódź lub most.")
        elif in_vehicle and vehicle_type in ("plane", "airplane", "heli", "helicopter"):
            priority_action = "Trzymaj [Spację] (lub [R]), aby zwiększyć ciąg i wznosić się samolotem lub helikopterem."
            suggestions.append("Używaj [Q] lub [Shift], aby płynnie obniżać wysokość przy lądowaniu.")
        elif not in_vehicle and not has_parachute:
            priority_action = "Dobierz spadochron w sklepie ($100), aby bezpiecznie wyskakiwać w locie."
        elif cash < 300:
            priority_action = "Okradnij sklep [J] lub weź darmowe Lamborghini z garażu [B] i ruszaj po gotówkę."
            suggestions.append("Po zebraniu funduszy możesz spróbować napadu na bank [H] lub lotu rakietą NASA.")
        else:
            priority_action = "Masz solidny zapas gotówki — wciśnij [X] dla AI Chaos Director, poleć na Księżyc lub przetestuj flotę aut."
            suggestions.append("W menu [ESC] możesz przejrzeć encyklopedię funkcji oraz ustawienia grafiki 64-bit.")

        return {
            "priorityAction": priority_action,
            "suggestions": suggestions,
            "repairedState": repaired,
            "appliedFixes": fixes,
            "statusSummary": f"HP: {hp} | Gotówka: ${cash} | Pościg: {stars}★ | Księżyc: {'TAK' if on_moon else 'NIE'}",
        }


class GroqGameplayAssistant:
    """Asystent AI oparty na Groq API z rotacją kluczy i bezpiecznym fallbackiem lokalnym."""

    def __init__(self, api_keys: list[str] | None = None, balancer: GameplayBalancer | None = None) -> None:
        env_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        keys = ([env_key] if env_key else []) + list(api_keys or DEFAULT_GROQ_KEYS)
        # Zachowujemy unikalne niepuste klucze w kolejności
        seen: set[str] = set()
        self.keys: list[str] = []
        for k in keys:
            kk = str(k or "").strip()
            if kk and kk not in seen:
                seen.add(kk)
                self.keys.append(kk)
        self._key_index = 0
        self.balancer = balancer or GameplayBalancer()

    def _try_simple_math(self, text: str) -> str | None:
        cleaned = text.strip().lower().replace(",", ".")
        # Obsługa prostych wyrażeń typu "ile to 2+2" lub "2 + 2 * 3"
        m = re.search(r"([0-9]+(?:\.[0-9]+)?(?:\s*[\+\-\*\/]\s*[0-9]+(?:\.[0-9]+)?)+)", cleaned)
        if not m:
            return None
        expr = m.group(1)
        if not re.fullmatch(r"[0-9\.\+\-\*\/\s]+", expr):
            return None
        try:
            result = eval(expr, {"__builtins__": {}}, {})
        except Exception:
            return None
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expr.strip()} = {result}"

    def _local_fallback(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        math_ans = self._try_simple_math(message)
        advice = self.balancer.advise_player(context)

        if math_ans:
            reply = f"Wynik obliczenia: **{math_ans}**. Jeśli potrzebujesz też wskazówki do gry: {advice['priorityAction']}"
        else:
            reply = (
                f"{advice['priorityAction']} "
                f"(Tryb lokalny / awaryjny — pytanie: „{message.strip()}”)."
            )

        return {
            "ok": True,
            "source": "local-fallback",
            "reply": reply,
            "advice": advice,
        }

    def ask(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt_text = str(message or "").strip()
        if not prompt_text:
            return self._local_fallback("co zrobić dalej?", context)

        advice = self.balancer.advise_player(context)
        system_prompt = (
            "Jesteś pomocnym, konkretnym asystentem AI w grze GTA SUS 3D: Infinity Edition. "
            "Odpowiadasz po polsku na każde pytanie: doradzasz co zrobić w grze (lot na Spacji, spadochron, "
            "napady [J]/[H], rakieta NASA na Księżyc, 400 pojazdów w tym Lamborghini, blokada wjazdu aut do wody), "
            "a także rozwiązujesz matematykę (np. 2+2) i odpowiadasz na pytania ogólne. "
            f"Aktualny stan gracza: {advice['statusSummary']}."
        )

        payload = {
            "model": GROQ_MODEL,
            "temperature": 0.65,
            "max_tokens": 500,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text},
            ],
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        total_keys = len(self.keys)
        for attempt in range(total_keys):
            idx = (self._key_index + attempt) % total_keys
            api_key = self.keys[idx]
            req = urllib.request.Request(
                GROQ_API_URL,
                data=body_bytes,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "GTA-SUS-3D-Python-Boost/10.64",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    choices = data.get("choices") or []
                    content = ((choices[0].get("message") or {}).get("content") or "").strip()
                    if content:
                        self._key_index = idx
                        return {
                            "ok": True,
                            "source": f"groq-key#{idx + 1}",
                            "reply": content,
                            "advice": advice,
                        }
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError):
                continue

        return self._local_fallback(prompt_text, context)


def write_gameplay_js(output_path: Path, profile: dict[str, Any]) -> None:
    """Eksportuje profil ulepszeń rozgrywki oraz pomocnik naprawy stanu do gameplay_tuning.js."""
    payload = json.dumps(profile, ensure_ascii=False, indent=2)
    js_content = f"""/**
 * gameplay_tuning.js — Wygenerowane automatycznie przez gta.py
 * Zawiera zbalansowane parametry rozgrywki i narzędzia do GTA SUS 3D: Infinity Edition.
 */
(function (global) {{
  'use strict';

  const GAMEPLAY_TUNING = {payload};

  global.GAMEPLAY_TUNING = GAMEPLAY_TUNING;
  global.GTA_SUS_GAMEPLAY_BOOST = {{
    profile: GAMEPLAY_TUNING,
    applyToGame(gameState) {{
      if (!gameState || typeof gameState !== 'object') return GAMEPLAY_TUNING;
      gameState.tuning = Object.assign({{}}, gameState.tuning || {{}}, GAMEPLAY_TUNING);
      if (typeof gameState.cash === 'number' && (!Number.isFinite(gameState.cash) || gameState.cash < 0)) {{
        gameState.cash = GAMEPLAY_TUNING.economy.startingCash;
      }}
      if (typeof gameState.hp === 'number' && (!Number.isFinite(gameState.hp) || gameState.hp < 0)) {{
        gameState.hp = 100;
      }}
      return gameState.tuning;
    }}
  }};
}})(typeof window !== 'undefined' ? window : globalThis);
"""
    output_path.write_text(js_content, encoding="utf-8")


def create_handler(balancer: GameplayBalancer, assistant: GroqGameplayAssistant):
    class GtaBoostHandler(BaseHTTPRequestHandler):
        def _send_json(self, code: int, data: dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            if self.path.startswith("/api/tuning"):
                self._send_json(200, {"ok": True, "tuning": balancer.build_tuning_profile()})
                return
            if self.path.startswith("/api/health"):
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "gta.py",
                        "groqKeysLoaded": len(assistant.keys),
                    },
                )
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "endpoints": ["/api/health", "/api/tuning", "/api/advisor", "/api/repair", "/api/chat"],
                },
            )

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body_raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body_raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "Niepoprawny JSON"})
                return

            if self.path.startswith("/api/repair"):
                repaired, fixes = StateSanitizer.repair_state(payload)
                self._send_json(200, {"ok": True, "repairedState": repaired, "fixes": fixes})
                return

            if self.path.startswith("/api/advisor"):
                advice = balancer.advise_player(payload)
                self._send_json(200, {"ok": True, "advice": advice})
                return

            if self.path.startswith("/api/chat"):
                message = str(payload.get("message") or payload.get("prompt") or "")
                context = payload.get("context") if isinstance(payload.get("context"), dict) else payload
                result = assistant.ask(message=message, context=context)
                self._send_json(200, result)
                return

            self._send_json(404, {"ok": False, "error": "Nieznany endpoint"})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return GtaBoostHandler


def run_self_test(balancer: GameplayBalancer, assistant: GroqGameplayAssistant) -> None:
    repaired, fixes = StateSanitizer.repair_state({"hp": -15, "cash": -500, "stars": 99, "inWater": True, "vehicleType": "car"})
    assert repaired["hp"] == 0 and repaired["cash"] == 0 and repaired["stars"] == 6 and repaired["blockCarInWater"] is True
    math_res = assistant._local_fallback("ile to 2+2?", {"cash": 1000, "hp": 100, "stars": 0})
    assert "4" in math_res["reply"]
    prof = balancer.build_tuning_profile()
    assert prof["vehiclesAndFlight"]["garageTotalVehicles"] == 400
    print(f"[SELF-TEST OK] Naprawiono {len(fixes)} błędów stanu; kluczy Groq: {len(assistant.keys)}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Moduł rozgrywki, naprawy błędów i AI dla GTA SUS 3D: Infinity Edition")
    parser.add_argument("--host", default="127.0.0.1", help="Adres hosta API (domyślnie 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port serwera API (domyślnie 8765)")
    parser.add_argument("--seed", default="DUBAI-SUS-64", help="Seed świata")
    parser.add_argument("--no-server", action="store_true", help="Tylko wygeneruj gameplay_tuning.js bez uruchamiania serwera")
    parser.add_argument("--self-test", action="store_true", help="Wykonaj szybki test działania i zakończ")
    args = parser.parse_args()

    balancer = GameplayBalancer(seed=args.seed, wanted_level=1, cash=1000)
    assistant = GroqGameplayAssistant(api_keys=DEFAULT_GROQ_KEYS, balancer=balancer)

    if args.self_test:
        run_self_test(balancer, assistant)
        return

    profile = balancer.build_tuning_profile()
    out_js = Path(__file__).resolve().parent / "gameplay_tuning.js"
    write_gameplay_js(out_js, profile)

    advice = balancer.advise_player({"cash": 1000, "hp": 100, "stars": 0, "inVehicle": False})
    print(f"[OK] Wygenerowano {out_js.name} (seed: {args.seed}, kluczy Groq: {len(assistant.keys)})")
    print(f"[PORADA] {advice['priorityAction']}")

    if args.no_server:
        return

    server = ThreadingHTTPServer((args.host, args.port), create_handler(balancer, assistant))
    print(f"[SERWER] Aktywny pod http://{args.host}:{args.port} (/api/tuning, /api/advisor, /api/repair, /api/chat)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Zatrzymano serwer gta.py")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

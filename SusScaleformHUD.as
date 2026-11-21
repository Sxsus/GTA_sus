package {
	import flash.display.Sprite;
	import flash.display.Shape;
	import flash.text.TextField;
	import flash.text.TextFormat;
	import flash.text.TextFieldAutoSize;
	import flash.events.Event;
	import flash.events.MouseEvent;
	import flash.events.KeyboardEvent;
	import flash.ui.Keyboard;
	import flash.net.URLLoader;
	import flash.net.URLRequest;
	import flash.net.URLRequestMethod;
	import flash.net.URLVariables;
	import flash.net.URLRequestHeader;

	/**
	 * SusScaleformHUD.as
	 * Moduł interfejsu (HUD, menu oraz ekran telefonu SusPhone [P]) w stylu Scaleform
	 * dla gry GTA SUS 3D: Infinity Edition.
	 *
	 * Obsługuje:
	 * - Górny HUD (gotówka, HP, gwiazdki pościgu 0..6, wysokość/pułap, stan spadochronu i rakiety NASA/Księżyca),
	 * - Ekran telefonu SusPhone [P] z zakładkami (AI Czat, Chaos [X], Garaż [B], Sklep [I], NASA/Księżyc),
	 * - Szybkie menu akcji [ESC] oraz wysyłanie zapytań do Groq AI z rotacją kluczy.
	 */
	public class SusScaleformHUD extends Sprite {

		public static const VERSION:String = "10.64-scaleform-as3";
		private static const GROQ_ENDPOINT:String = "https://api.groq.com/openai/v1/chat/completions";
		private static const GROQ_MODEL:String = "llama-3.3-70b-versatile";

		private var groqKeys:Vector.<String>;
		private var keyCursor:int = 0;

		// Stan rozgrywki synchronizowany z silnikiem gry
		private var hp:int = 100;
		private var cash:Number = 1000;
		private var stars:int = 0;
		private var altitude:Number = 0.0;
		private var onMoon:Boolean = false;
		private var parachuteOpen:Boolean = false;
		private var hasParachute:Boolean = true;
		private var vehicleName:String = "Pieszo";
		private var activeTab:String = "ai"; // "ai", "chaos", "garage", "moon"

		// Elementy wizualne HUD i telefonu
		private var hudBar:Sprite;
		private var cashText:TextField;
		private var hpText:TextField;
		private var starsText:TextField;
		private var telemetryText:TextField;

		private var phoneContainer:Sprite;
		private var phoneVisible:Boolean = false;
		private var phoneLogText:TextField;
		private var phoneInputText:TextField;
		private var phoneStatusText:TextField;

		private var pauseMenuContainer:Sprite;
		private var pauseVisible:Boolean = false;

		public function SusScaleformHUD() {
			initGroqKeyPool();
			if (stage != null) {
				setupStage();
			} else {
				addEventListener(Event.ADDED_TO_STAGE, onAddedToStage);
			}
		}

		private function onAddedToStage(e:Event):void {
			removeEventListener(Event.ADDED_TO_STAGE, onAddedToStage);
			setupStage();
		}

		private function initGroqKeyPool():void {
			groqKeys = new Vector.<String>();
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
			groqKeys.push("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");
		}

		private function setupStage():void {
			buildTopHud();
			buildSusPhone();
			buildPauseMenu();
			refreshHudLabels();

			stage.addEventListener(KeyboardEvent.KEY_DOWN, onKeyDown);
		}

		private function makeTextField(x:Number, y:Number, w:Number, h:Number, color:uint, size:int, bold:Boolean = false):TextField {
			var fmt:TextFormat = new TextFormat("Arial", size, color, bold);
			var tf:TextField = new TextField();
			tf.x = x;
			tf.y = y;
			tf.width = w;
			tf.height = h;
			tf.defaultTextFormat = fmt;
			tf.selectable = false;
			tf.wordWrap = true;
			return tf;
		}

		private function drawPanel(w:Number, h:Number, fillColor:uint, alphaVal:Number, borderColor:uint = 0x38BDF8, radius:Number = 10):Shape {
			var sh:Shape = new Shape();
			sh.graphics.lineStyle(1.5, borderColor, 0.75);
			sh.graphics.beginFill(fillColor, alphaVal);
			sh.graphics.drawRoundRect(0, 0, w, h, radius, radius);
			sh.graphics.endFill();
			return sh;
		}

		private function buildTopHud():void {
			hudBar = new Sprite();
			hudBar.x = 18;
			hudBar.y = 16;

			var bg:Shape = drawPanel(430, 86, 0x090D1A, 0.82, 0x38BDF8, 12);
			hudBar.addChild(bg);

			cashText = makeTextField(14, 8, 190, 26, 0x4ADE80, 16, true);
			hpText = makeTextField(210, 8, 205, 26, 0xF87171, 15, true);
			starsText = makeTextField(14, 34, 400, 22, 0xFACC15, 14, true);
			telemetryText = makeTextField(14, 56, 405, 24, 0xCBD5E1, 12, false);

			hudBar.addChild(cashText);
			hudBar.addChild(hpText);
			hudBar.addChild(starsText);
			hudBar.addChild(telemetryText);
			addChild(hudBar);
		}

		private function buildSusPhone():void {
			phoneContainer = new Sprite();
			phoneContainer.x = 860;
			phoneContainer.y = 70;
			phoneContainer.visible = false;

			var frame:Shape = drawPanel(340, 560, 0x0B1120, 0.94, 0xA855F7, 22);
			phoneContainer.addChild(frame);

			var titleTf:TextField = makeTextField(16, 14, 240, 26, 0xE9D5FF, 16, true);
			titleTf.text = "SusPhone [P] — Scaleform OS";
			phoneContainer.addChild(titleTf);

			var closeBtn:Sprite = createActionButton("X", 288, 12, 34, 26, 0xEF4444, function(e:MouseEvent):void {
				togglePhone(false);
			});
			phoneContainer.addChild(closeBtn);

			// Zakładki telefonu
			phoneContainer.addChild(createActionButton("AI Czat", 16, 48, 72, 26, 0x2563EB, function(e:MouseEvent):void {
				switchPhoneTab("ai");
			}));
			phoneContainer.addChild(createActionButton("Chaos [X]", 94, 48, 76, 26, 0xDC2626, function(e:MouseEvent):void {
				switchPhoneTab("chaos");
			}));
			phoneContainer.addChild(createActionButton("Garaż [B]", 176, 48, 76, 26, 0x059669, function(e:MouseEvent):void {
				switchPhoneTab("garage");
			}));
			phoneContainer.addChild(createActionButton("NASA", 258, 48, 66, 26, 0x7C3AED, function(e:MouseEvent):void {
				switchPhoneTab("moon");
			}));

			phoneStatusText = makeTextField(16, 80, 308, 22, 0x93C5FD, 11, true);
			phoneContainer.addChild(phoneStatusText);

			var logBg:Shape = drawPanel(308, 360, 0x020617, 0.9, 0x1E293B, 10);
			logBg.x = 16;
			logBg.y = 106;
			phoneContainer.addChild(logBg);

			phoneLogText = makeTextField(24, 114, 292, 344, 0xF1F5F9, 12, false);
			phoneLogText.selectable = true;
			phoneLogText.text = "Asystent SusPhone gotowy. Zapytaj o grę, matematykę (np. 2+2) albo wciśnij przycisk akcji.";
			phoneContainer.addChild(phoneLogText);

			var inputBg:Shape = drawPanel(224, 34, 0x0F172A, 1.0, 0x475569, 8);
			inputBg.x = 16;
			inputBg.y = 478;
			phoneContainer.addChild(inputBg);

			phoneInputText = makeTextField(22, 483, 212, 24, 0xFFFFFF, 13, false);
			phoneInputText.type = "input";
			phoneInputText.selectable = true;
			phoneInputText.text = "Ile to 2+2 i co zrobić dalej?";
			phoneContainer.addChild(phoneInputText);

			var sendBtn:Sprite = createActionButton("Wyślij", 246, 478, 78, 34, 0x16A34A, function(e:MouseEvent):void {
				sendPhonePrompt(phoneInputText.text);
			});
			phoneContainer.addChild(sendBtn);

			addChild(phoneContainer);
		}

		private function buildPauseMenu():void {
			pauseMenuContainer = new Sprite();
			pauseMenuContainer.x = 420;
			pauseMenuContainer.y = 150;
			pauseMenuContainer.visible = false;

			var bg:Shape = drawPanel(440, 340, 0x090D1A, 0.95, 0xF59E0B, 16);
			pauseMenuContainer.addChild(bg);

			var heading:TextField = makeTextField(24, 18, 392, 32, 0xFDE68A, 20, true);
			heading.text = "GTA SUS 3D: INFINITY EDITION — MENU";
			pauseMenuContainer.addChild(heading);

			var infoTf:TextField = makeTextField(24, 58, 392, 130, 0xE2E8F0, 13, false);
			infoTf.text =
				"• [Spacja / R] — Wznoszenie samolotu i helikoptera / otwarcie spadochronu w locie\n" +
				"• [B] — Garaż 400 pojazdów ($0), w tym flota Lamborghini\n" +
				"• [I] — Sklep ($100): jedzenie, spadochrony, pancerz\n" +
				"• [J] / [H] — Napady na sklepy i bank | [E] — Wnętrza i rakieta NASA\n" +
				"• [P] — Telefon SusPhone | [Y] — Mini AI Czat | [X] — AI Chaos";
			pauseMenuContainer.addChild(infoTf);

			pauseMenuContainer.addChild(createActionButton("Wznów grę [ESC]", 24, 210, 185, 38, 0x16A34A, function(e:MouseEvent):void {
				togglePauseMenu(false);
			}));
			pauseMenuContainer.addChild(createActionButton("Otwórz SusPhone [P]", 230, 210, 186, 38, 0x2563EB, function(e:MouseEvent):void {
				togglePauseMenu(false);
				togglePhone(true);
			}));
			pauseMenuContainer.addChild(createActionButton("Wywołaj Chaos [X]", 24, 260, 392, 38, 0xDC2626, function(e:MouseEvent):void {
				appendLog("[AI CHAOS] Aktywowano losowe wydarzenie w metropolii.");
				togglePauseMenu(false);
			}));

			addChild(pauseMenuContainer);
		}

		private function createActionButton(label:String, x:Number, y:Number, w:Number, h:Number, bgColor:uint, onClick:Function):Sprite {
			var btn:Sprite = new Sprite();
			btn.x = x;
			btn.y = y;
			btn.buttonMode = true;
			btn.mouseChildren = false;

			var bg:Shape = drawPanel(w, h, bgColor, 0.92, 0xFFFFFF, 7);
			btn.addChild(bg);

			var tf:TextField = makeTextField(2, Math.max(2, (h - 20) * 0.5), w - 4, 20, 0xFFFFFF, 11, true);
			tf.autoSize = TextFieldAutoSize.CENTER;
			tf.text = label;
			btn.addChild(tf);

			btn.addEventListener(MouseEvent.CLICK, onClick);
			return btn;
		}

		private function onKeyDown(e:KeyboardEvent):void {
			if (e.keyCode == Keyboard.P) {
				togglePhone(!phoneVisible);
			} else if (e.keyCode == Keyboard.ESCAPE) {
				if (phoneVisible) {
					togglePhone(false);
				} else {
					togglePauseMenu(!pauseVisible);
				}
			}
		}

		public function togglePhone(show:Boolean):void {
			phoneVisible = show;
			phoneContainer.visible = show;
			if (show) {
				switchPhoneTab(activeTab);
			}
		}

		public function togglePauseMenu(show:Boolean):void {
			pauseVisible = show;
			pauseMenuContainer.visible = show;
		}

		public function switchPhoneTab(tab:String):void {
			activeTab = tab;
			phoneStatusText.text = "Zakładka: " + tab.toUpperCase() + " | Pojazd: " + vehicleName;
			if (tab == "chaos") {
				appendLog("[CHAOS] Wybierz tryb szaleństwa w mieście albo wyślij własny pomysł w polu poniżej.");
			} else if (tab == "garage") {
				appendLog("[GARAŻ $0] Dostępnych 400 pojazdów (w tym Lamborghini Aventador, Huracán, Urus, Revuelto, Countach, Sián, samoloty, helikoptery i łodzie).");
			} else if (tab == "moon") {
				appendLog("[NASA / KSIĘŻYC] Podejdź do rakiety i naciśnij [E], aby polecieć na Księżyc lub wrócić na Ziemię.");
			}
		}

		public function syncGameState(state:Object):void {
			if (state == null) return;
			if ("hp" in state) hp = Math.max(0, Math.min(100, int(state.hp)));
			if ("cash" in state) cash = Math.max(0, Number(state.cash));
			if ("stars" in state) stars = Math.max(0, Math.min(6, int(state.stars)));
			if ("altitude" in state) altitude = Number(state.altitude);
			if ("onMoon" in state) onMoon = Boolean(state.onMoon);
			if ("parachuteOpen" in state) parachuteOpen = Boolean(state.parachuteOpen);
			if ("hasParachute" in state) hasParachute = Boolean(state.hasParachute);
			if ("vehicleName" in state && state.vehicleName) vehicleName = String(state.vehicleName);
			refreshHudLabels();
		}

		private function refreshHudLabels():void {
			if (cashText != null) cashText.text = "$" + int(cash);
			if (hpText != null) hpText.text = "HP: " + hp + "%";

			var starsStr:String = "";
			for (var i:int = 0; i < 6; i++) {
				starsStr += (i < stars) ? "★ " : "☆ ";
			}
			if (starsText != null) starsText.text = "POŚCIG: " + starsStr + "| " + vehicleName;

			var locStr:String = onMoon ? "KSIĘŻYC (niska grawitacja)" : "METROPOLIA";
			var paraStr:String = parachuteOpen ? "Spadochron: OTWARTY" : (hasParachute ? "Spadochron: GOTOWY" : "Spadochron: BRAK");
			if (telemetryText != null) {
				telemetryText.text = locStr + " | Wys.: " + altitude.toFixed(1) + "m | " + paraStr;
			}
		}

		public function appendLog(line:String):void {
			if (phoneLogText == null) return;
			var current:String = phoneLogText.text;
			phoneLogText.text = (current.length > 0 ? current + "\n\n" : "") + line;
			phoneLogText.scrollV = phoneLogText.maxScrollV;
		}

		public function sendPhonePrompt(prompt:String):void {
			var clean:String = prompt != null ? trimText(prompt) : "";
			if (clean.length == 0) return;

			appendLog("Ty: " + clean);
			phoneStatusText.text = "Łączenie z AI...";

			// Natychmiastowa odpowiedź lokalna dla prostych działań (np. 2+2) + próba Groq AI
			var quickMath:String = evalSimpleMath(clean);
			if (quickMath != null) {
				appendLog("AI: Wynik to " + quickMath + ". Potrzebujesz też podpowiedzi co zrobić w grze?");
				phoneStatusText.text = "Gotowe (szybkie obliczenie)";
				return;
			}

			requestGroqChat(clean);
		}

		private function requestGroqChat(userMessage:String):void {
			if (groqKeys == null || groqKeys.length == 0) {
				appendLog("AI (offline): " + buildLocalAdvice(userMessage));
				phoneStatusText.text = "Tryb offline";
				return;
			}

			var apiKey:String = groqKeys[keyCursor % groqKeys.length];
			keyCursor = (keyCursor + 1) % groqKeys.length;

			var sysMsg:String =
				"Jesteś asystentem AI w telefonie SusPhone w grze GTA SUS 3D: Infinity Edition. " +
				"Odpowiadasz po polsku, doradzasz co zrobić w grze, rozwiązujesz matematykę i odpowiadasz na pytania ogólne. " +
				"Stan gracza: HP=" + hp + ", kasa=$" + int(cash) + ", pościg=" + stars + "★, Księżyc=" + (onMoon ? "TAK" : "NIE") + ".";

			var payload:String =
				'{"model":"' + GROQ_MODEL + '","temperature":0.65,"max_tokens":380,"messages":[' +
				'{"role":"system","content":"' + jsonEscape(sysMsg) + '"},' +
				'{"role":"user","content":"' + jsonEscape(userMessage) + '"}' +
				']}';

			var req:URLRequest = new URLRequest(GROQ_ENDPOINT);
			req.method = URLRequestMethod.POST;
			req.data = payload;
			req.contentType = "application/json";
			req.requestHeaders.push(new URLRequestHeader("Authorization", "Bearer " + apiKey));

			var loader:URLLoader = new URLLoader();
			loader.addEventListener(Event.COMPLETE, function(e:Event):void {
				var raw:String = String(loader.data);
				var reply:String = extractContentField(raw);
				if (reply != null && reply.length > 0) {
					appendLog("AI: " + reply);
					phoneStatusText.text = "Połączono z Groq AI";
				} else {
					appendLog("AI (lokalnie): " + buildLocalAdvice(userMessage));
					phoneStatusText.text = "Tryb lokalny";
				}
			});
			loader.addEventListener("ioError", function(e:Event):void {
				appendLog("AI (lokalnie): " + buildLocalAdvice(userMessage));
				phoneStatusText.text = "Tryb lokalny (brak sieci)";
			});
			loader.addEventListener("securityError", function(e:Event):void {
				appendLog("AI (lokalnie): " + buildLocalAdvice(userMessage));
				phoneStatusText.text = "Tryb lokalny";
			});

			try {
				loader.load(req);
			} catch (err:Error) {
				appendLog("AI (lokalnie): " + buildLocalAdvice(userMessage));
				phoneStatusText.text = "Tryb lokalny";
			}
		}

		private function buildLocalAdvice(msg:String):String {
			if (onMoon) {
				return "Jesteś na Księżycu: skacz wysoko w niskiej grawitacji i użyj [E] przy rakiecie, aby wrócić na Ziemię.";
			}
			if (hp < 40) {
				return "Masz mało HP (" + hp + "%) — zjedz coś lub kup apteczkę w sklepie ($100) i uważaj na upadki bez spadochronu.";
			}
			if (stars >= 4) {
				return "Pościg " + stars + "★ — użyj nitro [N], mostów nad zatoką albo wejdź do wnętrza budynku [E].";
			}
			return "Możesz wziąć darmowe auto z garażu [B], polecieć samolotem lub helikopterem na Spacji, zrobić napad [J]/[H] albo polecieć rakietą NASA na Księżyc.";
		}

		private function evalSimpleMath(text:String):String {
			var normalized:String = text.replace(/,/g, ".");
			var match:Array = normalized.match(/(-?\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(-?\d+(?:\.\d+)?)/);
			if (match == null || match.length < 4) return null;

			var a:Number = Number(match[1]);
			var op:String = String(match[2]);
			var b:Number = Number(match[3]);
			if (isNaN(a) || isNaN(b)) return null;

			var res:Number = NaN;
			if (op == "+") res = a + b;
			else if (op == "-") res = a - b;
			else if (op == "*") res = a * b;
			else if (op == "/" && b != 0) res = a / b;

			if (isNaN(res) || !isFinite(res)) return null;
			return match[0] + " = " + String(res);
		}

		private function extractContentField(rawJson:String):String {
			if (rawJson == null) return null;
			var marker:String = '"content":"';
			var idx:int = rawJson.lastIndexOf(marker);
			if (idx == -1) return null;
			var start:int = idx + marker.length;
			var out:String = "";
			for (var i:int = start; i < rawJson.length; i++) {
				var ch:String = rawJson.charAt(i);
				if (ch == "\\" && i + 1 < rawJson.length) {
					var nx:String = rawJson.charAt(++i);
					if (nx == "n") out += "\n";
					else if (nx == "r") out += "";
					else if (nx == "t") out += "  ";
					else out += nx;
				} else if (ch == '"') {
					break;
				} else {
					out += ch;
				}
			}
			return out;
		}

		private function jsonEscape(s:String):String {
			if (s == null) return "";
			return s
				.replace(/\\/g, "\\\\")
				.replace(/"/g, '\\"')
				.replace(/\r/g, "")
				.replace(/\n/g, "\\n");
		}

		private function trimText(s:String):String {
			return s.replace(/^\s+|\s+$/g, "");
		}

		public function exportHudSnapshotJson():String {
			return '{"version":"' + VERSION + '","hp":' + hp + ',"cash":' + int(cash) +
				',"stars":' + stars + ',"altitude":' + altitude.toFixed(2) +
				',"onMoon":' + (onMoon ? "true" : "false") +
				',"parachuteOpen":' + (parachuteOpen ? "true" : "false") +
				',"vehicle":"' + jsonEscape(vehicleName) + '"}';
		}
	}
}

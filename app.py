import os
import re
import json
import time
import unicodedata
 
import streamlit as st
import paho.mqtt.client as paho
from bokeh.models.widgets import Button
from bokeh.models import CustomJS
from streamlit_bokeh_events import streamlit_bokeh_events
from PIL import Image
 
# ──────────────────────────────────────────────
# Configuración de página
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Control por Voz",
    page_icon="🎙️",
    layout="centered",
)
 
# ──────────────────────────────────────────────
# Comandos que entiende el ESP32 (Wokwi)
# "payload" es EXACTAMENTE el texto que compara el ESP32.
# ──────────────────────────────────────────────
COMMANDS = {
    "luz_on": {
        "emoji": "💡",
        "title": "Enciende las luces",
        "payload": "enciende las luces",
        "triggers": ["enciende las luces", "prende las luces", "encender luces"],
        "color": "#FBBF24",
    },
    "luz_off": {
        "emoji": "🌑",
        "title": "Apaga las luces",
        "payload": "apaga las luces",
        "triggers": ["apaga las luces", "apagar luces"],
        "color": "#64748B",
    },
    "puerta_on": {
        "emoji": "🚪",
        "title": "Abre la puerta",
        "payload": "abre la puerta",
        "triggers": ["abre la puerta", "abrir puerta"],
        "color": "#34D399",
    },
    "puerta_off": {
        "emoji": "🔒",
        "title": "Cierra la puerta",
        # Ojo: el código Wokwi compara "Cierra la puerta" con C mayúscula
        "payload": "Cierra la puerta",
        "triggers": ["cierra la puerta", "cerrar puerta"],
        "color": "#F87171",
    },
}
 
 
def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni signos, para comparar lo que escuchó el navegador."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
 
 
def match_command(text: str):
    t = normalize(text)
    for key, cmd in COMMANDS.items():
        if any(trig in t for trig in cmd["triggers"]):
            return key
    return None
 
 
# ──────────────────────────────────────────────
# Estado
# ──────────────────────────────────────────────
if "luces" not in st.session_state:
    st.session_state.luces = None      # True / False / None
if "puerta" not in st.session_state:
    st.session_state.puerta = None
if "last_key" not in st.session_state:
    st.session_state.last_key = None
if "historial" not in st.session_state:
    st.session_state.historial = []
 
# ──────────────────────────────────────────────
# Estilos
# ──────────────────────────────────────────────
st.markdown(
    """
<style>
    .stApp {
        background: radial-gradient(circle at 20% 0%, #1e1b4b 0%, #0f172a 45%, #020617 100%);
        color: #e2e8f0;
    }
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding-top: 2rem; max-width: 820px;}
 
    .hero {text-align: center; margin-bottom: 0.5rem;}
    .hero h1 {
        font-size: 2.4rem; font-weight: 800; margin: 0;
        background: linear-gradient(90deg, #38bdf8, #a78bfa, #f472b6);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .hero p {color: #94a3b8; letter-spacing: .25em; font-size: .8rem; margin-top: .2rem;}
 
    .section-title {
        font-size: 1rem; font-weight: 700; color: #cbd5e1;
        margin: 1.6rem 0 .6rem 0; letter-spacing: .05em;
    }
 
    .cmd-grid {display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;}
    .cmd-card {
        background: rgba(255,255,255,.04);
        border: 1px solid rgba(255,255,255,.10);
        border-radius: 18px; padding: 18px 16px; text-align: center;
        backdrop-filter: blur(6px);
        transition: all .25s ease;
    }
    .cmd-card:hover {transform: translateY(-3px); background: rgba(255,255,255,.07);}
    .cmd-card .emoji {font-size: 2.6rem; line-height: 1.2;}
    .cmd-card .title {font-weight: 700; font-size: 1.05rem; margin-top: 6px;}
    .cmd-card .hint {font-size: .75rem; color: #94a3b8; margin-top: 2px;}
    .cmd-card.active {
        box-shadow: 0 0 0 2px var(--c), 0 0 28px -4px var(--c);
        background: rgba(255,255,255,.09);
        animation: pulse 1.2s ease-in-out 2;
    }
    @keyframes pulse {50% {transform: scale(1.04);}}
 
    .status-row {display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;}
    .status {
        border-radius: 16px; padding: 14px; text-align: center;
        background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.10);
    }
    .status .big {font-size: 2rem;}
    .status .lbl {font-size: .75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .12em;}
    .status .val {font-weight: 700; font-size: 1rem;}
 
    .heard {
        background: rgba(56,189,248,.10); border-left: 4px solid #38bdf8;
        padding: 12px 16px; border-radius: 10px; margin-top: 10px;
    }
    .heard small {color: #94a3b8;}
    .hist {font-size: .85rem; color: #94a3b8; padding: 3px 0;}
 
    div[data-testid="stImage"] img {border-radius: 50%; border: 3px solid rgba(167,139,250,.6);}
</style>
""",
    unsafe_allow_html=True,
)
 
# ──────────────────────────────────────────────
# MQTT
# ──────────────────────────────────────────────
def on_publish(client, userdata, result):
    print("el dato ha sido publicado \n")
 
 
def on_message(client, userdata, message):
    global message_received
    time.sleep(2)
    message_received = str(message.payload.decode("utf-8"))
    st.write(message_received)
 
 
broker = "broker.mqttdashboard.com"
port = 1883
client1 = paho.Client("GIT-HUBC")
client1.on_message = on_message
 
# ──────────────────────────────────────────────
# Encabezado
# ──────────────────────────────────────────────
st.markdown(
    """
<div class="hero">
    <h1>🎙️ INTERFACES MULTIMODALES</h1>
    <p>CONTROL POR VOZ</p>
</div>
""",
    unsafe_allow_html=True,
)
 
col_a, col_b, col_c = st.columns([1, 1, 1])
with col_b:
    try:
        st.image(Image.open("voice_ctrl.jpg"), width=160)
    except Exception:
        st.markdown("<div style='text-align:center;font-size:4rem'>🎤</div>", unsafe_allow_html=True)
 
# ──────────────────────────────────────────────
# Botón de voz
# ──────────────────────────────────────────────
st.markdown('<div class="section-title">🎧 TOCA EL BOTÓN Y HABLA</div>', unsafe_allow_html=True)
 
stt_button = Button(label="🎙️  Iniciar escucha", width=220, button_type="primary")
 
stt_button.js_on_event("button_click", CustomJS(code="""
    var recognition = new webkitSpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'es-CO';
 
    recognition.onresult = function (e) {
        var value = "";
        for (var i = e.resultIndex; i < e.results.length; ++i) {
            if (e.results[i].isFinal) {
                value += e.results[i][0].transcript;
            }
        }
        if ( value != "") {
            document.dispatchEvent(new CustomEvent("GET_TEXT", {detail: value}));
        }
    }
    recognition.start();
    """))
 
result = streamlit_bokeh_events(
    stt_button,
    events="GET_TEXT",
    key="listen",
    refresh_on_update=False,
    override_height=75,
    debounce_time=0,
)
 
# ──────────────────────────────────────────────
# Procesar lo escuchado
# ──────────────────────────────────────────────
heard_text = None
active_key = None
unrecognized = False
 
if result and "GET_TEXT" in result:
    heard_text = result.get("GET_TEXT").strip()
    active_key = match_command(heard_text)
 
    if active_key:
        cmd = COMMANDS[active_key]
        client1.on_publish = on_publish
        client1.connect(broker, port)
        message = json.dumps({"Act1": cmd["payload"]})
        client1.publish("voice_ctrl", message)
 
        # Actualizar estado visual
        if active_key == "luz_on":
            st.session_state.luces = True
        elif active_key == "luz_off":
            st.session_state.luces = False
        elif active_key == "puerta_on":
            st.session_state.puerta = True
        elif active_key == "puerta_off":
            st.session_state.puerta = False
 
        st.session_state.last_key = active_key
        st.session_state.historial.insert(0, f"{cmd['emoji']} {cmd['title']}")
        st.session_state.historial = st.session_state.historial[:5]
    else:
        unrecognized = True
 
    try:
        os.mkdir("temp")
    except Exception:
        pass
 
# ──────────────────────────────────────────────
# Lo que se escuchó
# ──────────────────────────────────────────────
if heard_text:
    if active_key:
        cmd = COMMANDS[active_key]
        st.markdown(
            f"""<div class="heard"><small>Escuché</small><br>
            <b>“{heard_text}”</b> → {cmd['emoji']} <b>{cmd['title']}</b> enviado ✅</div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""<div class="heard" style="border-color:#f87171;background:rgba(248,113,113,.10)">
            <small>Escuché</small><br><b>“{heard_text}”</b> → ❓ comando no reconocido</div>""",
            unsafe_allow_html=True,
        )
 
# ──────────────────────────────────────────────
# Estado de los dispositivos
# ──────────────────────────────────────────────
def estado(valor, on_txt, off_txt, on_emoji, off_emoji):
    if valor is None:
        return "⚪", "Sin datos"
    return (on_emoji, on_txt) if valor else (off_emoji, off_txt)
 
 
luz_e, luz_t = estado(st.session_state.luces, "Encendidas", "Apagadas", "💡", "🌑")
pue_e, pue_t = estado(st.session_state.puerta, "Abierta", "Cerrada", "🚪", "🔒")
 
st.markdown('<div class="section-title">📡 ESTADO DEL SISTEMA</div>', unsafe_allow_html=True)
st.markdown(
    f"""
<div class="status-row">
    <div class="status"><div class="big">{luz_e}</div><div class="lbl">Luces</div><div class="val">{luz_t}</div></div>
    <div class="status"><div class="big">{pue_e}</div><div class="lbl">Puerta</div><div class="val">{pue_t}</div></div>
</div>
""",
    unsafe_allow_html=True,
)
 
# ──────────────────────────────────────────────
# Comandos disponibles
# ──────────────────────────────────────────────
st.markdown('<div class="section-title">🗣️ COMANDOS DISPONIBLES</div>', unsafe_allow_html=True)
 
cards = ""
for key, cmd in COMMANDS.items():
    cls = "cmd-card active" if key == st.session_state.last_key and active_key == key else "cmd-card"
    cards += f"""
    <div class="{cls}" style="--c:{cmd['color']}">
        <div class="emoji">{cmd['emoji']}</div>
        <div class="title">{cmd['title']}</div>
        <div class="hint">Di: “{cmd['title']}”</div>
    </div>"""
 
st.markdown(f'<div class="cmd-grid">{cards}</div>', unsafe_allow_html=True)
 
# ──────────────────────────────────────────────
# Historial
# ──────────────────────────────────────────────
if st.session_state.historial:
    st.markdown('<div class="section-title">🕘 ÚLTIMOS COMANDOS</div>', unsafe_allow_html=True)
    for h in st.session_state.historial:
        st.markdown(f'<div class="hist">{h}</div>', unsafe_allow_html=True)
 

import sys
import os
import time
import subprocess
import base64
import tempfile
import threading
import signal
import logging
import json
import re

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QIcon, QAction

import keyboard
import pyperclip
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
from openai import OpenAI
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app_debug.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Vibecoder")

# Load environment variables
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Constants
SAMPLE_RATE = 44100
CHANNELS = 1
DTYPE = 'int16'

def get_clipboard_content():
    """
    Retrieves content from clipboard. 
    Prioritizes file paths (CF_HDROP) if available, otherwise returns text.
    """
    # 1. Try getting file paths via PowerShell (Windows specific)
    try:
        # Get-Clipboard -Format FileDropList returns a list of files
        cmd = "Get-Clipboard -Format FileDropList | Select-Object -ExpandProperty FullName"
        result = subprocess.run(
            ["powershell", "-Command", cmd], 
            capture_output=True, 
            text=True, 
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        files = result.stdout.strip()
        if files:
            logger.debug(f"Clipboard contains files: {files}")
            return files
    except Exception as e:
        logger.warning(f"Failed to get clipboard files: {e}")

    # 2. Fallback to text
    try:
        text = pyperclip.paste()
        return text
    except Exception as e:
        logger.error(f"Failed to get clipboard text: {e}")
        return ""

# --- Worker Threads ---

class AudioRecorder(QObject):
    finished = pyqtSignal(str)  # Emits path to temporary wav file
    
    def __init__(self):
        super().__init__()
        self.recording = False
        self.frames = []
        self.stream = None
        logger.debug("AudioRecorder initialized")
        
    def start_recording(self):
        if self.recording:
            return
        logger.info("Starting recording...")
        self.recording = True
        self.frames = []
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, callback=self.callback)
            self.stream.start()
        except Exception as e:
            logger.error(f"Error starting audio: {e}", exc_info=True)
            self.recording = False
        
    def callback(self, indata, frames, time, status):
        if status:
            logger.warning(f"Audio callback status: {status}")
        if self.recording:
            self.frames.append(indata.copy())
            
    def stop_recording(self):
        if not self.recording:
            return
        logger.info("Stopping recording...")
        self.recording = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.error(f"Error closing stream: {e}", exc_info=True)
            self.stream = None
            
        if not self.frames:
            logger.warning("No frames recorded")
            self.finished.emit("")
            return

        recording_data = np.concatenate(self.frames, axis=0)
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                wav.write(temp_audio.name, SAMPLE_RATE, recording_data)
                logger.info(f"Audio saved to {temp_audio.name}")
                self.finished.emit(temp_audio.name)
        except Exception as e:
            logger.error(f"Error saving audio: {e}", exc_info=True)
            self.finished.emit("")

class AIWorker(QObject):
    transcription_finished = pyqtSignal(str)
    task_finished = pyqtSignal(str, str) # mode, content
    error_occurred = pyqtSignal(str)
    
    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key
        self.last_resolved_path = None # State to remember the last file worked on
        
    def transcribe(self, audio_path):
        logger.info(f"Transcribing audio: {audio_path}")
        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
            )
            
            with open(audio_path, "rb") as audio_file:
                audio_data = base64.b64encode(audio_file.read()).decode("utf-8")
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe the following audio verbatim. Output ONLY the text. Do not add any introduction or explanation."},
                        {"type": "input_audio", "input_audio": {"data": audio_data, "format": "wav"}}
                    ]
                }
            ]
            
            completion = client.chat.completions.create(
                model="google/gemini-2.5-flash",
                messages=messages
            )
            
            text = completion.choices[0].message.content.strip()
            logger.info(f"Transcription result: {text}")
            self.transcription_finished.emit(text)
            
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            self.error_occurred.emit(f"Transcription failed: {str(e)}")
        # Note: We do NOT delete the audio file here anymore, as we might need it for YOLO/Coding

    def _resolve_file_path(self, text, strict=False):
        """
        Attempts to resolve a file path from the given text.
        If strict=True, text must BE the path (with optional line numbers).
        If strict=False, searches for a path within the text.
        """
        if not text: return None
        
        def check_path(p):
            p = p.strip()
            # Remove quotes
            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                p = p[1:-1]
            
            # Handle line numbers by stripping from end (e.g. file.py:10, file.py:10:5)
            candidate = p
            while len(candidate) > 1:
                if os.path.exists(candidate) and os.path.isfile(candidate):
                    return candidate
                
                # Strip last :digits
                match = re.search(r'(:\d+)$', candidate)
                if match:
                    candidate = candidate[:match.start()]
                else:
                    break
            return None

        # 1. Strict check (entire text is a path)
        res = check_path(text)
        if res: return res
        
        if strict: return None
        
        # 2. Search in text (for YOLO logs etc)
        # Check quoted strings
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        for q in quoted:
            s = q[0] if q[0] else q[1]
            res = check_path(s)
            if res: return res
            
        # Check tokens (whitespace separated)
        tokens = text.split()
        for token in tokens:
            # Clean up common punctuation
            token = token.strip(".,;:()[]{}'\"")
            res = check_path(token)
            if res: return res
            
        return None

    def process_request(self, context, instruction, audio_path=None, mode="coding"):
        logger.info(f"Processing request. Mode: {mode}, Audio: {audio_path}")
        
        # Always try to resolve a file path from the context (even loosely)
        # This handles cases where the user selects an error log or a file path.
        resolved_path = self._resolve_file_path(context, strict=False)
        
        if resolved_path:
            logger.info(f"Resolved file path: {resolved_path}")
            self.last_resolved_path = resolved_path # Remember this file
        elif mode == "yolo" and self.last_resolved_path:
            # If YOLO mode and no path found in selection, use the last known file
            logger.info(f"No path in context, using last resolved path: {self.last_resolved_path}")
            resolved_path = self.last_resolved_path

        # Prepare Context based on Mode and Resolved Path
        if mode == "coding":
            if resolved_path:
                try:
                    with open(resolved_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                    # Append file content to the original context (which might be an error message)
                    context = f"Original Selection:\n{context}\n\n--- Content of {resolved_path} ---\n{file_content}"
                    logger.info(f"Loaded file content from {resolved_path}")
                except Exception as e:
                    logger.error(f"Failed to read file {resolved_path}: {e}")
            # If no path resolved, context remains the original selection (likely code snippet)

        elif mode == "yolo":
            if resolved_path:
                # For YOLO, we prioritize the file path as the target for execution
                # We keep the original context if it's different, but ensure the path is clear
                if context != resolved_path:
                     context = f"Target File: {resolved_path}\n\nContext Info:\n{context}"
                else:
                     context = resolved_path
                logger.info(f"YOLO Context set to target: {resolved_path}")

        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
            )
            
            messages = []
            model = "google/gemini-2.5-flash" # Default to Gemini for multimodal support

            if mode == "yolo":
                system_prompt = "You are a Windows PowerShell expert. Output ONLY the command to execute. No markdown, no explanation, no code blocks. Just the raw command string."
                messages.append({"role": "system", "content": system_prompt})
                
                # Check if we have audio to decide model
                if audio_path and os.path.exists(audio_path):
                    # Use Gemini for YOLO to support audio input
                    model = "google/gemini-2.5-flash"
                    
                    user_content = []
                    text_content = f"Instruction: {instruction}"
                    if context:
                        text_content += f"\nContext:\n{context}"
                    
                    user_content.append({"type": "text", "text": text_content})
                    
                    logger.debug("Attaching audio to YOLO request")
                    with open(audio_path, "rb") as audio_file:
                        audio_data = base64.b64encode(audio_file.read()).decode("utf-8")
                        user_content.append({
                            "type": "input_audio", 
                            "input_audio": {"data": audio_data, "format": "wav"}
                        })
                    
                    messages.append({"role": "user", "content": user_content})
                else:
                    # No audio, use Grok for text-only YOLO (faster/preferred)
                    model = "x-ai/grok-code-fast-1"
                    user_content = f"Instruction: {instruction}"
                    if context:
                        user_content += f"\nContext:\n{context}"
                    messages.append({"role": "user", "content": user_content})
                
            else: # coding mode
                # Use Grok for coding (fast, good code)
                model = "x-ai/grok-code-fast-1"
                
                system_prompt = """You are an expert coding assistant. 
                Your task is to modify the provided code context based on the user's instruction.
                
                CRITICAL RULES:
                1. Output ONLY the modified code.
                2. Do NOT include any markdown formatting (no ```python, no ```).
                3. Do NOT include any explanations, introductions, or conclusions.
                4. The output must be ready to be pasted directly into an IDE to replace the original code.
                """
                messages.append({"role": "system", "content": system_prompt})
                
                user_content = f"Instruction: {instruction}"
                if context:
                    user_content += f"\nContext:\n{context}"
                messages.append({"role": "user", "content": user_content})

            completion = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://vibecoder.com",
                    "X-Title": "Vibecoder HUD",
                },
                model=model,
                messages=messages
            )
            
            result = completion.choices[0].message.content
            
            # Post-processing
            if result.startswith("```"):
                lines = result.split('\n')
                if len(lines) >= 2:
                    result = "\n".join(lines[1:-1])
            
            logger.info("AI response received")
            self.task_finished.emit(mode, result)
            
        except Exception as e:
            logger.error(f"AI processing error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            # Clean up audio file after processing request
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    logger.debug(f"Deleted temp audio file: {audio_path}")
                except:
                    pass

# --- Signal Bridge for Keyboard ---
class KeyBridge(QObject):
    on_voice_start = pyqtSignal()
    on_voice_stop = pyqtSignal()
    on_action = pyqtSignal()
    on_cancel = pyqtSignal()
    on_reset = pyqtSignal()
    on_yolo = pyqtSignal()

    def emit_voice_start(self):
        self.on_voice_start.emit()

    def emit_voice_stop(self):
        logger.info("KeyBridge: emit_voice_stop")
        self.on_voice_stop.emit()

    def emit_action(self):
        self.on_action.emit()

    def emit_cancel(self):
        self.on_cancel.emit()

    def emit_reset(self):
        self.on_reset.emit()

    def emit_yolo(self):
        self.on_yolo.emit()

# --- HUD Window ---

class HUDWindow(QWidget):
    def __init__(self):
        super().__init__()
        logger.debug("Initializing HUDWindow")
        self.initUI()
        
        # States: IDLE, RECORDING, TRANSCRIBING, READY, THINKING, REVIEW, YOLO_THINKING, YOLO_EXECUTING
        self.state = "IDLE"
        
        self.audio_recorder = AudioRecorder()
        
        # AI Worker Thread
        self.ai_thread = QThread()
        self.ai_worker = AIWorker(OPENROUTER_API_KEY)
        self.ai_worker.moveToThread(self.ai_thread)
        self.ai_thread.start()
        
        # Connect signals
        self.audio_recorder.finished.connect(self.on_audio_recorded)
        self.ai_worker.transcription_finished.connect(self.on_transcription_finished)
        self.ai_worker.task_finished.connect(self.on_ai_task_finished)
        self.ai_worker.error_occurred.connect(self.on_ai_error)
        
        self.current_instruction = ""
        self.current_context = ""
        self.current_audio_path = None # Store audio path
        self.generated_content = ""

        self.show_startup_message()

    def initUI(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        screen = QApplication.primaryScreen().geometry()
        width = 600
        height = 400
        self.setGeometry(screen.width() - width - 50, 50, width, height)
        
        layout = QVBoxLayout()
        
        # Status Label
        self.status_label = QLabel("IDLE")
        self.status_label.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)
        
        # Helper Label (Button Hints)
        self.hint_label = QLabel("")
        self.hint_label.setFont(QFont("Consolas", 9))
        self.hint_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.hint_label)

        # Content Area
        self.text_area = QTextEdit()
        self.text_area.setFont(QFont("Consolas", 10))
        self.text_area.setStyleSheet("""
            background-color: rgba(30, 30, 30, 230);
            color: #d4d4d4;
            border: none;
            border-radius: 8px;
            padding: 10px;
        """)
        self.text_area.setReadOnly(True)
        layout.addWidget(self.text_area)
        
        self.setLayout(layout)
        
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 30, 230);
                border-radius: 8px;
            }
        """)

    def show_startup_message(self):
        self.status_label.setText("Vibecoder HUD Ready")
        self.status_label.setStyleSheet("color: #00ff00;")
        self.text_area.setText("System initialized.\n\nWaiting for record (F2)...")
        self.show()
        QTimer.singleShot(3000, lambda: self.update_state("IDLE"))

    def update_state(self, state):
        logger.info(f"State update: {self.state} -> {state}")
        self.state = state
        
        if state == "IDLE":
            self.status_label.setText("IDLE")
            self.status_label.setStyleSheet("color: gray;")
            self.hint_label.setText("Voice: record (F2)")
            self.hide()
            
        elif state == "RECORDING":
            self.status_label.setText("LISTENING [REC]")
            self.status_label.setStyleSheet("color: red;")
            self.hint_label.setText("Release to Finish")
            self.show()
            
        elif state == "TRANSCRIBING":
            self.status_label.setText("TRANSCRIBING...")
            self.status_label.setStyleSheet("color: cyan;")
            self.hint_label.setText("Please wait...")
            self.show()
            
        elif state == "READY":
            self.status_label.setText("READY")
            self.status_label.setStyleSheet("color: white;")
            self.hint_label.setText("Action: Execute (F3) | YOLO: Shell (F6) | Cancel (F1)")
            self.show()
            
        elif state == "THINKING":
            self.status_label.setText("THINKING...")
            self.status_label.setStyleSheet("color: cyan;")
            self.hint_label.setText("Cancel (F1)")
            self.show()
            
        elif state == "REVIEW":
            self.status_label.setText("REVIEW")
            self.status_label.setStyleSheet("color: yellow;")
            self.hint_label.setText("Action: Accept (F3) | Cancel: Reject (F1)")
            self.show()
            
        elif state == "SUCCESS":
            self.status_label.setText("SUCCESS")
            self.status_label.setStyleSheet("color: green;")
            self.hint_label.setText("")
            QTimer.singleShot(1500, lambda: self.update_state("IDLE"))
            
        elif state == "YOLO_EXECUTING":
            self.status_label.setText("EXECUTING YOLO...")
            self.status_label.setStyleSheet("color: magenta;")
            self.hint_label.setText("Cancel (F1)")
            self.show()

    # --- Event Handlers ---

    def start_listening(self):
        if self.state == "IDLE" or self.state == "READY" or self.state == "REVIEW":
            self.update_state("RECORDING")
            self.text_area.clear()
            self.audio_recorder.start_recording()

    def stop_listening(self):
        logger.info(f"stop_listening called. Current state: {self.state}")
        if self.state == "RECORDING":
            self.update_state("TRANSCRIBING")
            QApplication.processEvents() 
            self.audio_recorder.stop_recording()

    def on_audio_recorded(self, path):
        if not path:
            self.update_state("IDLE")
            return
        self.current_audio_path = path # Save path for later use
        # Start transcription
        QTimer.singleShot(0, lambda: self.ai_worker.transcribe(path))

    def on_transcription_finished(self, text):
        self.current_instruction = text
        self.text_area.setText(f"> {text}")
        self.update_state("READY")

    def trigger_action(self):
        logger.debug(f"Action triggered in state: {self.state}")
        
        if self.state == "READY":
            # Start Coding Mode
            self.update_state("THINKING")
            # Capture Context
            old_clipboard = pyperclip.paste()
            keyboard.send('ctrl+c')
            QTimer.singleShot(200, self._process_coding_context)
            
        elif self.state == "REVIEW":
            # Accept Code
            logger.info("Accepting code")
            pyperclip.copy(self.generated_content)
            self.hide()
            QTimer.singleShot(200, lambda: keyboard.send('ctrl+v'))
            self.update_state("SUCCESS")

    def _process_coding_context(self):
        self.current_context = get_clipboard_content()
        logger.debug(f"Context captured: {len(self.current_context)} chars")
        QTimer.singleShot(0, lambda: self.ai_worker.process_request(
            self.current_context, 
            self.current_instruction, 
            self.current_audio_path,
            mode="coding"
        ))

    def trigger_yolo(self):
        logger.debug(f"YOLO triggered in state: {self.state}")
        
        if self.state == "READY":
            # Start YOLO Mode
            self.update_state("THINKING") 
            # Capture Context (Optional but good for errors)
            keyboard.send('ctrl+c')
            QTimer.singleShot(200, self._process_yolo_context)

    def _process_yolo_context(self):
        self.current_context = get_clipboard_content()
        QTimer.singleShot(0, lambda: self.ai_worker.process_request(
            self.current_context, 
            self.current_instruction, 
            self.current_audio_path,
            mode="yolo"
        ))

    def on_ai_task_finished(self, mode, result):
        self.current_audio_path = None # Clear audio path after use
        
        if mode == "coding":
            self.generated_content = result
            # For display, we wrap it in markdown if it's not already
            display_text = result
            if not result.startswith("```"):
                display_text = f"```\n{result}\n```"
            self.text_area.setMarkdown(display_text)
            self.update_state("REVIEW")
            
        elif mode == "yolo":
            self.update_state("YOLO_EXECUTING")
            self.text_area.setMarkdown(f"```powershell\n{result}\n```\n\n**EXECUTING...**")
            
            # Execute Shell Command
            try:
                # Clean up command (remove markdown if any remains)
                cmd = result.replace("```powershell", "").replace("```bash", "").replace("```", "").strip()
                
                process = subprocess.Popen(
                    ["powershell", "-Command", cmd], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                stdout, stderr = process.communicate()
                output = stdout + stderr
                self.text_area.append(f"\n**Output:**\n```\n{output}\n```")
            except Exception as e:
                self.text_area.append(f"\nError: {e}")
                
            # Stay in YOLO_EXECUTING or go to READY? 
            # Let's stay visible so user can see output, until Cancel is pressed.

    def on_ai_error(self, error_msg):
        self.text_area.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("color: red;")
        # Allow user to cancel or retry
        self.state = "READY" # Fallback to ready so they can try again? Or IDLE?
        self.hint_label.setText("Error occurred. Press Cancel.")
        self.current_audio_path = None

    def cancel_action(self):
        logger.debug("Cancel triggered")
        if self.state == "RECORDING":
            self.audio_recorder.stop_recording()
            self.update_state("IDLE")
        else:
            self.update_state("IDLE")
            self.text_area.clear()
            self.current_audio_path = None

    def reset_context(self):
        logger.debug("Reset triggered")
        self.current_instruction = ""
        self.current_context = ""
        self.generated_content = ""
        self.current_audio_path = None
        self.text_area.clear()
        self.update_state("IDLE")
        self.show_startup_message() # Briefly show "Ready"

# --- Main Application ---

def main():
    logger.info("Application starting...")
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    hud = HUDWindow()
    bridge = KeyBridge()
    
    # Tray Icon
    tray_icon = QSystemTrayIcon(QIcon(), app)
    from PyQt6.QtGui import QPixmap, QColor, QPainter
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor("cyan"))
    painter.drawEllipse(0, 0, 16, 16)
    painter.end()
    tray_icon.setIcon(QIcon(pixmap))
    
    tray_menu = QMenu()
    show_action = QAction("Show/Hide HUD", app)
    show_action.triggered.connect(lambda: hud.setVisible(not hud.isVisible()))
    quit_action = QAction("Quit", app)
    quit_action.triggered.connect(app.quit)
    tray_menu.addAction(show_action)
    tray_menu.addAction(quit_action)
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    
    # Connect Bridge
    bridge.on_voice_start.connect(hud.start_listening)
    bridge.on_voice_stop.connect(hud.stop_listening)
    bridge.on_action.connect(hud.trigger_action)
    bridge.on_cancel.connect(hud.cancel_action)
    bridge.on_reset.connect(hud.reset_context)
    bridge.on_yolo.connect(hud.trigger_yolo)
    
    # Register Hotkeys
    try:
        logger.info("Registering hotkeys...")
        keyboard.add_hotkey('alt+shift+f2', bridge.emit_voice_start)
        keyboard.on_release_key('f2', lambda e: bridge.emit_voice_stop())
        keyboard.add_hotkey('alt+shift+f3', bridge.emit_action)
        keyboard.add_hotkey('alt+shift+f1', bridge.emit_cancel)
        keyboard.add_hotkey('alt+shift+f7', bridge.emit_reset)
        keyboard.add_hotkey('alt+shift+f6', bridge.emit_yolo)
        logger.info("Hotkeys registered.")
    except Exception as e:
        logger.critical(f"Failed to hook keys: {e}")

    app.aboutToQuit.connect(lambda: keyboard.unhook_all())

    print("Vibecoder HUD Running.")
    print("Hotkeys: Alt+Shift+F1/F2/F3/F7/F6")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
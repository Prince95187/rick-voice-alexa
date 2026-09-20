import asyncio
import os
import subprocess
import uuid
import numpy as np
import soundfile as sf
import torch
import edge_tts
import infer_rvc_python.main as rvc_main

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "RickSanchez.pth")

# Global singleton loader
_NET_G = None
_VC = None
_TGT_SR = None
_HUBERT = None
_CFG = None
_INITIALIZED = False


def init_models():
    global _NET_G, _VC, _TGT_SR, _HUBERT, _CFG, _INITIALIZED
    if _INITIALIZED:
        return True

    if not os.path.exists(MODEL_PATH):
        print(f"[RVC] Model not found at {MODEL_PATH}")
        return False

    try:
        print("[RVC] Pre-loading RVC model and HuBERT into memory...")
        _CFG = rvc_main.Config(only_cpu=True)
        (
            n_spk,
            _TGT_SR,
            _NET_G,
            _VC,
            cpt,
            version,
        ) = rvc_main.load_trained_model(MODEL_PATH, _CFG)
        _HUBERT = rvc_main.load_hu_bert(_CFG)
        _INITIALIZED = True
        print(f"[RVC] Ready! Target Sample Rate: {_TGT_SR}Hz, Model: {version}")
        return True
    except Exception as e:
        print(f"[RVC] Initialization error: {e}")
        return False


async def text_to_speech_edge(text: str, output_path: str):
    """Generate clean baseline speech with Microsoft Edge TTS."""
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural", rate="+5%", pitch="-1Hz")
    await communicate.save(output_path)


def convert_audio_to_rick(input_audio_path: str, output_mp3_path: str):
    """Convert baseline speech to Rick Sanchez using PyTorch RVC."""
    if not _INITIALIZED:
        if not init_models():
            raise RuntimeError("RVC model could not be loaded")

    audio = rvc_main.load_audio(input_audio_path, 16000)
    audio_pad = np.pad(audio, (_VC.t_pad, _VC.t_pad), mode="reflect")
    p_len = audio_pad.shape[0] // _VC.window

    # Pitch tracking with Parselmouth
    pitch, pitchf = _VC.get_f0(input_audio_path, audio_pad, p_len, 0, "pm", 3, None)
    pitch = torch.tensor(pitch[:p_len]).unsqueeze(0).long()
    pitchf = torch.tensor(pitchf[:p_len]).unsqueeze(0).float()
    sid = torch.tensor(0).unsqueeze(0).long()
    times = [0, 0, 0]

    # Neural voice conversion
    out = _VC.vc(
        _HUBERT,
        _NET_G,
        sid,
        audio_pad,
        pitch,
        pitchf,
        times,
        None,
        None,
        0,
        "v2",
        0.33,
    )

    out = out[_VC.t_pad_tgt : -_VC.t_pad_tgt]
    audio_max = np.abs(out).max() / 0.99
    max_int16 = 32768
    if audio_max > 1:
        max_int16 /= audio_max
    audio_opt = (out * max_int16).astype(np.int16)

    # Save as standard Alexa-compliant MP3 (24000Hz, 48kbps, mono)
    temp_wav = f"/tmp/raw_{uuid.uuid4()}.wav"
    try:
        sf.write(temp_wav, audio_opt, _TGT_SR)
        # Convert with ffmpeg to ensure valid MP3 for Alexa SSML
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_wav,
            "-ac", "1",
            "-ar", "24000",
            "-b:a", "48k",
            "-codec:a", "libmp3lame",
            output_mp3_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            # Fallback if libmp3lame fails
            subprocess.run(["ffmpeg", "-y", "-i", temp_wav, output_mp3_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception:
                pass

    return output_mp3_path


async def synthesize_rick(text: str, output_file: str) -> str:
    """Full pipeline: Text -> Edge-TTS -> RVC conversion -> Rick Sanchez Audio."""
    temp_id = str(uuid.uuid4())
    temp_edge = f"/tmp/edge_{temp_id}.mp3"

    try:
        await text_to_speech_edge(text, temp_edge)
        loop = asyncio.get_running_loop()
        final_file = await loop.run_in_executor(None, convert_audio_to_rick, temp_edge, output_file)
        return final_file
    finally:
        if os.path.exists(temp_edge):
            try:
                os.remove(temp_edge)
            except Exception:
                pass

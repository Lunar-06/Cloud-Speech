from fireredasr2s.fireredpunc.punc import FireRedPunc, FireRedPuncConfig
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import fastapi_cdn_host
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import tempfile
import uuid
from typing import Any
import subprocess
import logging
import torch
import torchaudio
import librosa
import numpy as np

import sys
import os
os.environ["TRANSFORMERS_NO_TORCHCODEC"] = "1"

def get_base_dir() -> str:
    """返回可执行文件所在的目录（开发时返回脚本所在目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
base = get_base_dir()

def load_normal_audio_model():
    logger.info("正在加载普通话语音识别模型...")
    from fireredasr.models.fireredasr import FireRedAsr
    base = get_base_dir()
    model_path = os.path.join(base, "language_models", "foundation_modal")
    model = FireRedAsr.from_pretrained("aed", model_path)
    logger.info("普通话语音识别模型加载完成")
    return model

def add_punctuation(text: str) -> str:
    """对识别文本恢复标点，失败时回退原文本"""
    global punc_model

    if not text:
        return text

    if punc_model is None:
        return text

    try:
        results = punc_model.process([text])
        if isinstance(results, list) and len(results) > 0 and isinstance(results[0], dict):
            return results[0].get("punc_text", text)
        return text
    except Exception as e:
        logger.warning(f"标点恢复失败，返回原文本: {e}")
        return text

def format_dialect_results(original_results: Any) -> list:
    """将方言识别结果格式化为前端期望的格式，并恢复标点"""
    formatted_results = []

    try:
        if isinstance(original_results, list) and len(original_results) > 0:
            main_result = original_results[0]

            if isinstance(main_result, dict):
                text = main_result.get("text", "")
                text = add_punctuation(str(text))
                confidence = main_result.get("confidence", 1.0)
                formatted_results.append({
                    "confidence": float(confidence),
                    "text": text
                })

            elif isinstance(main_result, str):
                text = add_punctuation(main_result)
                formatted_results.append({
                    "confidence": 1.0,
                    "text": text
                })

            elif hasattr(main_result, "__dict__"):
                text = getattr(main_result, "text", getattr(main_result, "hypothesis", str(main_result)))
                text = add_punctuation(str(text))
                confidence = getattr(main_result, "confidence", getattr(main_result, "score", 1.0))
                formatted_results.append({
                    "confidence": float(confidence),
                    "text": text
                })

        elif isinstance(original_results, dict):
            text = original_results.get("text", original_results.get("hypothesis", ""))
            text = add_punctuation(str(text))
            confidence = original_results.get("confidence", original_results.get("score", 1.0))
            formatted_results.append({
                "confidence": float(confidence),
                "text": text
            })

        elif isinstance(original_results, str):
            text = add_punctuation(original_results)
            formatted_results.append({
                "confidence": 1.0,
                "text": text
            })

    except Exception as e:
        logger.error(f"格式化结果失败: {e}")

    return formatted_results

def check_audio_file(file_path: str) -> tuple:
    """检查音频文件是否可读，返回是否可以读取和音频信息"""
    try:
        import soundfile as sf
        info = sf.info(file_path)
        logger.info(f"音频文件信息 - 采样率: {info.samplerate}, 声道: {info.channels}, "
                    f"时长: {info.duration:.2f}秒, 格式: {info.subtype}, 文件大小: {os.path.getsize(file_path)} 字节")
        return True, info
    except Exception as e:
        logger.error(f"检查音频文件失败 {file_path}: {e}")
        return False, None

def is_kaldi_compatible_wav(file_path: str) -> bool:
    """检查WAV文件是否是kaldiio兼容的格式（PCM格式，非浮点）"""
    try:
        import soundfile as sf
        info = sf.info(file_path)

        if not file_path.lower().endswith('.wav'):
            return False

        subtype = info.subtype
        if 'PCM' in subtype:
            return True
        else:
            logger.warning(f"WAV文件格式不支持: {subtype}，需要转换为PCM格式")
            return False
    except Exception as e:
        logger.error(f"检查kaldi兼容性失败 {file_path}: {e}")
        return False

def get_ffmpeg_path():
    base = get_base_dir()
    ffmpeg_exe = os.path.join(base, "tools", "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        return ffmpeg_exe
    return "ffmpeg"

def convert_audio_with_ffmpeg(input_path: str, output_path: str, target_format: str = "wav") -> bool:
    """使用ffmpeg转换音频格式"""
    try:
        ffmpeg_cmd = get_ffmpeg_path()
        cmd = [
            ffmpeg_cmd, '-i', input_path,
            '-ar', '16000',
            '-ac', '1',
            '-acodec', 'pcm_s16le',
            '-f', target_format,
            '-y',
            output_path
        ]
        logger.info(f"执行FFmpeg转换命令: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            logger.error(f"FFmpeg转换失败，返回码: {result.returncode}")
            logger.error(f"FFmpeg错误输出: {result.stderr[:500]}")
            return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            logger.info(f"FFmpeg转换成功，文件大小: {os.path.getsize(output_path)} 字节")
            return True
        else:
            logger.error("转换后的文件不存在或太小")
            return False

    except subprocess.TimeoutExpired:
        logger.error("音频转换超时")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg未找到，请确保FFmpeg已安装并在PATH中")
        return False
    except Exception as e:
        logger.error(f"FFmpeg转换异常: {e}")
        return False

def convert_audio_with_pydub(input_path: str, output_path: str) -> bool:
    """使用pydub转换音频格式（备用方法）"""
    try:
        from pydub import AudioSegment
        from pydub.utils import which

        if not which("ffmpeg"):
            logger.error("pydub需要ffmpeg，但未找到")
            return False

        audio = AudioSegment.from_file(input_path)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(output_path, format="wav", parameters=["-acodec", "pcm_s16le"])

        logger.info(f"pydub转换成功，文件大小: {os.path.getsize(output_path)} 字节")
        return True

    except ImportError:
        logger.warning("pydub未安装，跳过此转换方法")
        return False
    except Exception as e:
        logger.error(f"pydub转换失败: {e}")
        return False

def convert_audio_with_soundfile(input_path: str, output_path: str) -> bool:
    """使用soundfile转换音频格式（备用方法2）"""
    try:
        import soundfile as sf

        data, samplerate = sf.read(input_path)

        if len(data.shape) > 1 and data.shape[1] > 1:
            data = data[:, 0]

        if data.dtype != np.int16:
            if data.dtype == np.float32 or data.dtype == np.float64:
                data = (data * 32767).astype(np.int16)
            else:
                data = data.astype(np.int16)

        target_sr = 16000
        if samplerate != target_sr:
            data = librosa.resample(data, orig_sr=samplerate, target_sr=target_sr)
            samplerate = target_sr

        sf.write(output_path, data, samplerate, subtype='PCM_16')

        logger.info(f"soundfile转换成功，文件大小: {os.path.getsize(output_path)} 字节")
        return True

    except ImportError:
        logger.warning("soundfile未安装，跳过此转换方法")
        return False
    except Exception as e:
        logger.error(f"soundfile转换失败: {e}")
        return False

def convert_to_wav(input_path: str, output_path: str) -> bool:
    """将音频文件转换为16kHz 16-bit PCM格式的wav文件，使用多种方法尝试"""
    logger.info(f"开始转换音频文件: {input_path} -> {output_path}")

    if not os.path.exists(input_path):
        logger.error(f"输入文件不存在: {input_path}")
        return False

    if input_path.lower().endswith('.wav'):
        if is_kaldi_compatible_wav(input_path):
            try:
                import shutil
                shutil.copy2(input_path, output_path)
                logger.info("文件已经是kaldi兼容的WAV格式，直接复制")
                return True
            except Exception as e:
                logger.error(f"复制文件失败: {e}")
        else:
            logger.info("WAV文件不是kaldi兼容格式，需要转换")

    if convert_audio_with_ffmpeg(input_path, output_path):
        return True

    if convert_audio_with_pydub(input_path, output_path):
        return True

    if convert_audio_with_soundfile(input_path, output_path):
        return True

    logger.error("所有音频转换方法都失败")
    return False


# 全局模型变量
dialect_model = None
normal_model = None
punc_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global dialect_model, punc_model, normal_model

    gpu_available = torch.cuda.is_available()
    gpu_count = torch.cuda.device_count() if gpu_available else 0
    current_device = torch.cuda.current_device() if gpu_available else "CPU"

    logger.info(f"GPU可用: {gpu_available}")
    if gpu_available:
        logger.info(f"GPU数量: {gpu_count}")
        logger.info(f"当前设备: {current_device}")
        for i in range(gpu_count):
            logger.info(f"GPU {i}: {torch.cuda.get_device_name(i)}")
    else:
        logger.info("使用CPU进行推理")

    # 加载方言识别模型
    try:
        logger.info("正在加载方言语音识别模型...")
        from fireredasr.models.fireredasr import FireRedAsr
        base = get_base_dir()
        model_path = os.path.join(base, "language_models", "test_dayemodel")
        dialect_model = FireRedAsr.from_pretrained("aed", model_path)
        logger.info("方言语音识别模型加载完成")
    except Exception as e:
        logger.error(f"方言语音识别模型加载失败: {e}")
        dialect_model = None

    # 加载普通话识别模型
    try:
        normal_model = load_normal_audio_model()
    except Exception as e:
        logger.error(f"普通话语音识别模型加载失败: {e}")
        normal_model = None

    # 加载标点恢复模型
    try:
        logger.info("正在加载标点恢复模型...")
        punc_config = FireRedPuncConfig(use_gpu=torch.cuda.is_available())
        base = get_base_dir()
        punc_path = os.path.join(base, "nltk", "FireRedPunc")
        punc_model = FireRedPunc.from_pretrained(punc_path, punc_config)
        logger.info("标点恢复模型加载完成")
    except Exception as e:
        logger.error(f"标点恢复模型加载失败: {e}")
        punc_model = None

    yield


app = FastAPI(
    title="语音识别API",
    description="方言语音识别 + 普通话语音识别 + 自动标点恢复",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5175", "http://127.0.0.1:5175",
        "http://localhost:5176", "http://127.0.0.1:5176",
        "http://localhost:5177", "http://127.0.0.1:5177",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fastapi_cdn_host.patch_docs(app)


@app.get("/")
async def root():
    return {
        "message": "语音识别API服务运行中",
        "status": "healthy",
        "features": ["方言语音识别", "普通话语音识别", "自动标点恢复"]
    }


@app.post("/dialect-recognition")
async def dialect_recognition(
        file: UploadFile = File(..., description="上传的方言音频文件"),
        use_gpu: int = 1,
        beam_size: int = 3,
        nbest: int = 1,
        decode_max_len: int = 0,
        softmax_smoothing: float = 1.0,
        aed_length_penalty: float = 0.0,
        eos_penalty: float = 1.0
):
    if dialect_model is None:
        raise HTTPException(status_code=503, detail="方言识别模型未加载完成，请稍后重试")

    allowed_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.webm'}
    file_extension = os.path.splitext(file.filename)[1].lower()

    allowed_mime_types = {
        'audio/mp3', 'audio/mpeg', 'audio/wav', 'audio/x-wav',
        'audio/mp4', 'audio/flac', 'audio/aac', 'audio/webm'
    }

    if (file_extension not in allowed_extensions and
            file.content_type not in allowed_mime_types):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。支持格式: {', '.join(allowed_extensions)}"
        )

    temp_input_path = None
    temp_wav_path = None

    try:
        actual_extension = file_extension
        if file.content_type == 'audio/webm' and file_extension != '.webm':
            actual_extension = '.webm'

        with tempfile.NamedTemporaryFile(delete=False, suffix=actual_extension) as temp_input:
            content = await file.read()
            temp_input.write(content)
            temp_input_path = temp_input.name

        uttid = str(uuid.uuid4())

        temp_wav_path = tempfile.mktemp(suffix='.wav')
        if not convert_to_wav(temp_input_path, temp_wav_path):
            raise HTTPException(status_code=500, detail="音频文件转换失败")

        audio_path = temp_wav_path

        batch_uttid = [uttid]
        batch_wav_path = [audio_path]

        decode_config = {
            "use_gpu": use_gpu,
            "beam_size": beam_size,
            "nbest": nbest,
            "decode_max_len": decode_max_len,
            "softmax_smoothing": softmax_smoothing,
            "aed_length_penalty": aed_length_penalty,
            "eos_penalty": eos_penalty
        }

        raw_results = dialect_model.transcribe(batch_uttid, batch_wav_path, decode_config)
        formatted_results = format_dialect_results(raw_results)

        response_data = {
            "success": True,
            "model_type": "dialect_recognition",
            "utterance_id": uttid,
            "original_filename": file.filename,
            "file_size": len(content),
            "file_type": file.content_type,
            "results": formatted_results
        }

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"方言语音识别失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"方言语音识别处理失败: {str(e)}")
    finally:
        for temp_file in [temp_input_path, temp_wav_path]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {temp_file}: {e}")


@app.post("/normal-recognition")
async def normal_recognition(
        file: UploadFile = File(..., description="上传的普通话音频文件"),
        use_gpu: int = 1,
        beam_size: int = 3,
        nbest: int = 1,
        decode_max_len: int = 0,
        softmax_smoothing: float = 1.0,
        aed_length_penalty: float = 0.0,
        eos_penalty: float = 1.0
):
    if normal_model is None:
        raise HTTPException(status_code=503, detail="普通话识别模型未加载完成，请稍后重试")

    allowed_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.webm'}
    file_extension = os.path.splitext(file.filename)[1].lower()

    allowed_mime_types = {
        'audio/mp3', 'audio/mpeg', 'audio/wav', 'audio/x-wav',
        'audio/mp4', 'audio/flac', 'audio/aac', 'audio/webm'
    }

    if (file_extension not in allowed_extensions and
            file.content_type not in allowed_mime_types):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。支持格式: {', '.join(allowed_extensions)}"
        )

    temp_input_path = None
    temp_wav_path = None

    try:
        actual_extension = file_extension
        if file.content_type == 'audio/webm' and file_extension != '.webm':
            actual_extension = '.webm'

        with tempfile.NamedTemporaryFile(delete=False, suffix=actual_extension) as temp_input:
            content = await file.read()
            temp_input.write(content)
            temp_input_path = temp_input.name

        uttid = str(uuid.uuid4())

        temp_wav_path = tempfile.mktemp(suffix='.wav')
        if not convert_to_wav(temp_input_path, temp_wav_path):
            raise HTTPException(status_code=500, detail="音频文件转换失败")

        audio_path = temp_wav_path

        batch_uttid = [uttid]
        batch_wav_path = [audio_path]

        decode_config = {
            "use_gpu": use_gpu,
            "beam_size": beam_size,
            "nbest": nbest,
            "decode_max_len": decode_max_len,
            "softmax_smoothing": softmax_smoothing,
            "aed_length_penalty": aed_length_penalty,
            "eos_penalty": eos_penalty
        }

        raw_results = normal_model.transcribe(batch_uttid, batch_wav_path, decode_config)
        formatted_results = format_dialect_results(raw_results)

        response_data = {
            "success": True,
            "model_type": "normal_recognition",
            "utterance_id": uttid,
            "original_filename": file.filename,
            "file_size": len(content),
            "file_type": file.content_type,
            "results": formatted_results
        }

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"普通话语音识别失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"普通话语音识别处理失败: {str(e)}")
    finally:
        for temp_file in [temp_input_path, temp_wav_path]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {temp_file}: {e}")


@app.get("/health")
async def health_check():
    status = {
        "dialect_model_loaded": dialect_model is not None,
        "normal_model_loaded": normal_model is not None,
        "overall_status": "healthy" if (dialect_model is not None and normal_model is not None) else "degraded"
    }

    if dialect_model is None or normal_model is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "message": "部分模型未加载",
                "details": status
            }
        )
    return {"status": "healthy", "message": "所有服务正常运行", "details": status}


@app.options("/{rest_of_path:path}")
async def preflight_handler(request: Request, rest_of_path: str):
    return JSONResponse(
        content={"message": "Preflight request handled"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS, DELETE, PUT",
            "Access-Control-Allow-Headers": "*",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

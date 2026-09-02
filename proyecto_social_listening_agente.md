# Proyecto: Agente de Social Listening y Clipping Automático de Video

Este documento contiene la arquitectura, el stack tecnológico y la hoja de ruta para el desarrollo de un mini proyecto escalable de automatización. El sistema "escucha" palabras clave (marcas o personas) en redes sociales, descarga los videos asociados, procesa el audio mediante IA y realiza un recorte (*clipping*) inteligente de forma autónoma.

---

## 🛠️ Arquitectura General del Sistema

El flujo de trabajo combina la orquestación visual de **n8n**, la potencia de procesamiento y analítica de **Python**, y la robustez estructural para futuras migraciones en **Go/Java**.

```
[Redes Sociales] ➔ [Monitoreo/Scraping] ➔ [Orquestador: n8n]
                                                │
                                                ▼
                                    [Python: Whisper (Audio a Texto)]
                                                │
                                                ▼
                                    [Agente de IA: Razonamiento/Llama3/GPT]
                                                │
                                                ▼
                                    [Python/FFmpeg: Clipping de Video]
                                                │
                                                ▼
                                    [Almacenamiento y Dashboard de Analytics]
```

### Flujo de Datos Paso a Paso:
1. **Captura (n8n / Go):** n8n ejecuta consultas periódicas o recibe webhooks desde APIs de scraping (como Apify) para detectar nuevas publicaciones con videos y palabras clave.
2. **Filtrado y Orquestación (n8n):** Filtra los datos relevantes y envía la URL del post al entorno de ejecución de Python.
3. **Transcripción (Python + Whisper):** Se descarga el video mediante `yt-dlp` y la librería Whisper procesa el audio para generar un JSON con el texto y sus marcas de tiempo (*timestamps*) exactas.
4. **Razonamiento (Agente de IA):** Un LLM evalúa la transcripción, determina el fragmento de mayor impacto o valor sobre la marca y decide los segundos exactos de inicio y fin.
5. **Acción/Edición (Python + FFmpeg):** El script corta el video de forma matemática basándose en la decisión del agente.
6. **Enriquecimiento (Analítica de Datos):** Se realiza un análisis de sentimiento sobre los comentarios del post original y se guardan las métricas (*likes*, vistas) para alimentar un dashboard.

---

## 🧰 Stack Tecnológico Recomendado

| Componente | Herramienta / Tecnología | Rol en el Proyecto |
| :--- | :--- | :--- |
| **Orquestador** | [n8n](https://n8n.io) (Local con Docker) | Conector de APIs, lógica de flujos y activación de agentes. |
| **Descarga de Medios** | `yt-dlp` (Python / CLI) | Extracción de videos desde Instagram, TikTok, X, YouTube, etc. |
| **Procesamiento de Audio**| `openai-whisper` (Python) | Conversión de voz a texto estructurado con marcas de tiempo. |
| **Cerebro / LLM** | GPT-4o o Llama 3 via [Groq](https://groq.com) | Agente inteligente que decide los puntos de corte y redacta copies. |
| **Edición de Video** | `FFmpeg` o `MoviePy` (Python) | Corte y renderizado del clip final. |
| **Framework de Agentes**| [CrewAI](https://www.crewai.com) o [LangGraph](https://www.langchain.com/langgraph) | Definición de roles autónomos (Editor, Analista). |
| **Visualización** | [Streamlit](https://streamlit.io) (Python) | Dashboard rápido para analizar métricas de las palabras clave. |

---

## 💾 Configuración Inicial del Entorno (Docker)

Para montar tu laboratorio de desarrollo local, utiliza el siguiente archivo `docker-compose.yml`. Este expone un volumen compartido para que tus scripts de Python y n8n puedan intercambiar los archivos de video descargados.

```yaml
version: '3.8'

services:
  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n_laboratorio
    ports:
      - "5678:5678"
    environment:
      - GENERIC_TIMEZONE=America/Argentina/Buenos_Aires
    volumes:
      - n8n_data:/home/node/.n8n
      # Carpeta compartida local para almacenar los videos descargados y procesados
      - ./compartido:/data 
    restart: always

volumes:
  n8n_data:
```

---

## 🐍 Código Base del Prototipo (Python)

Este script simula el comportamiento del nodo de acción. Recibe la URL desde n8n, descarga el video y realiza un corte inicial:

```python
import sys
import json
import subprocess
from moviepy.editor import VideoFileClip

def procesar_video(url, palabra_clave):
    print(f"Procesando URL: {url} para la marca: {palabra_clave}")
    
    # 1. Descarga del video usando yt-dlp
    nombre_archivo = "compartido/video_temp.mp4"
    comando_descarga = f"yt-dlp -o {nombre_archivo} {url}"
    subprocess.run(comando_descarga, shell=True, check=True)
    
    # 2. Clipping básico (En la fase con IA, Whisper y el LLM definirán estos tiempos)
    output_clip = f"compartido/clip_{palabra_clave}.mp4"
    with VideoFileClip(nombre_archivo) as video:
        clip = video.subclip(0, 15) # Primeros 15 segundos para el MVP
        clip.write_videofile(output_clip, codec="libx264", audio_codec="aac")
        
    # 3. Retornar respuesta estructurada para n8n
    resultado = {
        "status": "success",
        "archivo_generado": output_clip,
        "palabra_clave": palabra_clave
    }
    print(json.dumps(resultado))

if __name__ == "__main__":
    # Captura argumentos pasados desde el nodo 'Execute Command' de n8n
    if len(sys.argv) > 2:
        url_post = sys.argv[1]
        keyword = sys.argv[2]
        procesar_video(url_post, keyword)
```

---

## 🚀 Hoja de Ruta y Escalabilidad

Dado tu perfil técnico en **Java y Go**, el proyecto está estructurado para escalar orgánicamente en tres etapas bien definidas:

1. **Fase 1 (MVP - Monolítico Local):** n8n se conecta por CLI a tus scripts locales de Python. Toda la descarga, transcripción con Whisper y corte se realiza de forma secuencial en tu máquina.
2. **Fase 2 (Concurrencia con Go):** Reemplazas las herramientas de scraping de terceros creando microservicios de recolección en **Go**. Aprovechas las *goroutines* para escuchar cientos de palabras clave simultáneamente en múltiples redes y envías los datos limpios a n8n mediante HTTP Requests.
3. **Fase 3 (Arquitectura Empresarial Asíncrona):** n8n deja de ejecutar scripts directamente. Ahora actúa como el despachador de tareas, enviando las URLs a una cola de mensajería como **RabbitMQ** o **Apache Kafka**. Un pool de *workers* robustos en **Java (Spring Boot)** o Python consumen de la cola para procesar descargas y renderizado de video en paralelo sin saturar el servidor principal.
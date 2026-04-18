"""
Synkro - AI-Powered Workspace Orchestration System
Main FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db, close_db
from app.routers import auth, tasks, meetings, chat, integrations, analytics, emails, messages
from app.routers import admin
from app.routers import slack_webhooks
from app.routers import direct_messages

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown"""
    # Startup
    print(f"[*] Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"[*] Environment: {settings.ENVIRONMENT}")

    # Check critical configuration
    print("\n[*] Configuration Check:")

    # AI API Keys (for meeting transcription + summarization)
    if settings.GROQ_API_KEY:
        print("    [OK] Groq API Key: Configured (FREE transcription + summarization)")
    elif settings.OPENAI_API_KEY:
        print("    [OK] OpenAI API Key: Configured (paid)")
    else:
        print("    [X] No AI API Key configured!")
        print("      WARNING: Meeting transcription will not work!")
        print("      Get a FREE key at: https://console.groq.com/keys")

    # Storage configuration
    if settings.use_s3:
        print("    [OK] Storage: AWS S3")
    elif settings.use_cloudinary:
        print("    [OK] Storage: Cloudinary")
    else:
        print("    [!] Storage: Local filesystem (development only)")

    # Database
    db_type = "PostgreSQL" if "postgresql" in settings.DATABASE_URL else "SQLite"
    print(f"    [OK] Database: {db_type}")

    # Redis/Celery
    if settings.REDIS_URL:
        print("    [OK] Redis: Configured")
    else:
        print("    [X] Redis: Not configured (background tasks disabled)")

    print("")

    # Initialize database - create tables on startup
    try:
        await init_db()
    except Exception as e:
        print(f"[!] DB init warning (non-fatal): {e}")

    yield

    # Shutdown
    print("[*] Shutting down application")
    await close_db()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Powered Workspace Orchestration System for Software Development Teams",
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add GZip middleware for response compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include routers
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(meetings.router)
app.include_router(chat.router)
app.include_router(integrations.router)
app.include_router(slack_webhooks.router)  # Slack events webhook
app.include_router(analytics.router)
app.include_router(emails.router)
app.include_router(messages.router)
app.include_router(admin.router)
app.include_router(direct_messages.router)

# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - API information
    """
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "AI-Powered Workspace Orchestration System",
        "docs": "/api/docs",
        "status": "operational"
    }



# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring
    """
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION
    }


# API status endpoint
@app.get("/api/status", tags=["Status"])
async def api_status():
    """
    API status endpoint with feature availability
    """
    return {
        "status": "operational",
        "features": {
            "authentication": True,
            "task_management": True,
            "meeting_transcription": bool(settings.GROQ_API_KEY or settings.OPENAI_API_KEY),
            "file_storage": settings.use_s3 or settings.use_cloudinary,
            "integrations": {
                "gmail": bool(settings.GOOGLE_CLIENT_ID),
                "slack": bool(settings.SLACK_CLIENT_ID)
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development"
    )

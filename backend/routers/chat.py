from fastapi import APIRouter, HTTPException

from image_processing.compositor import compose_meme
from nlp.intent_router import parse_intent
from schemas import ChatRequest, ChatResponse, ChatMessage
from vector_db.chroma_client import log_usage, query_similar_memes

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main conversational endpoint.

    Flow:
      1. NLP layer parses the user message into a structured IntentResponse.
      2. ChromaDB is queried to surface contextually similar past memes.
      3. Pillow compositor renders the meme and returns a static URL.
      4. Usage is logged back to ChromaDB for future retrieval.
    """
    # Step 1 — intent routing
    intent = await parse_intent(request.message)

    # Step 2 — optional: surface similar past memes for context (not blocking)
    _context = query_similar_memes(request.message, n_results=3)

    # Step 3 — generate image
    try:
        meme_url = await compose_meme(
            template_id=intent.template_id,
            top_text=intent.top_text,
            bottom_text=intent.bottom_text,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Step 4 — log usage
    log_usage(
        template_id=intent.template_id,
        top_text=intent.top_text,
        bottom_text=intent.bottom_text,
        conversation_id=request.conversation_id or "",
    )

    reply = ChatMessage(
        role="assistant",
        content=f"{intent.top_text} / {intent.bottom_text}",
        meme_url=meme_url,
    )

    return ChatResponse(
        conversation_id=request.conversation_id or "",
        message=reply,
        template_used=intent.template_id,
    )

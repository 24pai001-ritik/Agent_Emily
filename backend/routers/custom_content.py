"""
API endpoints for Custom Content Creation Agent
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

def clean_for_json(obj):
    """Recursively clean object to ensure JSON serializability"""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Convert any other type to string
        return str(obj)
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from agents.custom_content_agent import CustomContentAgent, CustomContentState, ConversationStep
from auth import get_current_user

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom-content", tags=["custom-content"])

# Initialize the custom content agent
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

custom_content_agent = CustomContentAgent(openai_api_key)
custom_content_graph = custom_content_agent.create_graph()

# In-memory storage for conversation states (in production, use Redis or database)
conversation_states: Dict[str, CustomContentState] = {}

class StartConversationRequest(BaseModel):
    user_id: str

class UserInputRequest(BaseModel):
    conversation_id: str
    user_input: str
    input_type: str = "text"

class MediaUploadRequest(BaseModel):
    conversation_id: str
    filename: str
    content_type: str

@router.post("/start")
async def start_conversation(
    request: StartConversationRequest,
    current_user: dict = Depends(get_current_user)
):
    """Start a new custom content creation conversation"""
    try:
        # Create initial state
        initial_state: CustomContentState = {
            "user_id": request.user_id,
            "conversation_id": "",
            "conversation_messages": [],
            "current_step": ConversationStep.GREET,
            "selected_platform": None,
            "selected_content_type": None,
            "user_description": None,
            "has_media": None,
            "media_type": None,
            "uploaded_media_url": None,
            "should_generate_media": None,
            "generated_content": None,
            "generated_media_url": None,
            "final_post": None,
            "error_message": None,
            "platform_content_types": None,
            "media_requirements": None,
            "user_profile": None,
            "business_context": None,
            "is_complete": False,
            "progress_percentage": 0,
            # Carousel fields
            "carousel_images": None,
            "carousel_image_source": None,
            "current_carousel_index": 0,
            "carousel_max_images": 10,
            "uploaded_carousel_images": None,
            "carousel_upload_done": False,
            "carousel_theme": None
        }
        
        # Run only the first step (greet_user) to get the initial greeting
        result = await custom_content_agent.greet_user(initial_state)
        
        # Store the conversation state
        conversation_id = result["conversation_id"]
        conversation_states[conversation_id] = result
        
        return {
            "conversation_id": conversation_id,
            "message": result["conversation_messages"][-1],
            "current_step": result["current_step"],
            "progress_percentage": result["progress_percentage"]
        }
        
    except Exception as e:
        logger.error(f"Error starting conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start conversation: {str(e)}")

@router.post("/input")
async def process_user_input(
    request: UserInputRequest,
    current_user: dict = Depends(get_current_user)
):
    """Process user input in the conversation using LangGraph"""
    try:
        conversation_id = request.conversation_id
        
        # Get conversation state
        if conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        # Execute the conversation step using LangGraph
        result = await custom_content_agent.execute_conversation_step(
            state, request.user_input
        )
        
        # Update conversation state
        conversation_states[conversation_id] = result
        
        # Return the latest message and state
        latest_message = result["conversation_messages"][-1] if result["conversation_messages"] else {
            "role": "assistant",
            "content": "No message available",
            "timestamp": datetime.now().isoformat()
        }
        
        # Check if message already has script (from generation/regeneration)
        # If not, try to get it from script_id in database
        if not latest_message.get("script"):
            # If message has script_id, fetch the full script from content_posts table
            if latest_message.get("script_id"):
                try:
                    script_record = custom_content_agent.supabase.table("content_posts").select("*").eq("id", latest_message["script_id"]).execute()
                    if script_record.data and script_record.data[0]:
                        script_data = script_record.data[0].get("video_scripting")  # Fetch from video_scripting column
                        if script_data:
                            latest_message["script"] = script_data
                            logger.info(f"✅ Fetched script from content_posts for script_id: {latest_message['script_id']}")
                except Exception as e:
                    logger.error(f"Error fetching script from content_posts: {e}")
            # Also try to fetch from content_posts table if draft_id/script_post_id is available
            elif latest_message.get("draft_id") or latest_message.get("script_post_id"):
                script_id_to_fetch = latest_message.get("script_post_id") or latest_message.get("draft_id")
                try:
                    script_record = custom_content_agent.supabase.table("content_posts")\
                        .select("*")\
                        .eq("id", script_id_to_fetch)\
                        .execute()
                    if script_record.data and script_record.data[0]:
                        script_data = script_record.data[0].get("video_scripting")  # Use video_scripting column
                        if script_data:
                            latest_message["script"] = script_data
                            logger.info(f"✅ Fetched script from content_posts for script_id: {script_id_to_fetch}")
                except Exception as e:
                    logger.error(f"Error fetching script from content_posts: {e}")
            # If no script_id or draft_id, try to get from state["generated_script"]
            elif result.get("generated_script"):
                latest_message["script"] = result.get("generated_script")
                logger.info(f"✅ Added script from state['generated_script'] to message")
        else:
            logger.info(f"✅ Script already present in message: {list(latest_message.get('script', {}).keys())}")
        
        # Ensure script is in the message before returning
        if not latest_message.get("script") and result.get("generated_script"):
            latest_message["script"] = result.get("generated_script")
            logger.info(f"✅ Added script from state to message before returning")
        
        # Ensure all_scripts and script_history are included if available
        if result.get("script_history"):
            # If message doesn't have all_scripts, add them
            if not latest_message.get("all_scripts"):
                latest_message["all_scripts"] = [s["script"] for s in result["script_history"]]
                logger.info(f"✅ Added all_scripts to message: {len(latest_message['all_scripts'])} scripts")
            
            # If message doesn't have script_history, add it
            if not latest_message.get("script_history"):
                latest_message["script_history"] = result["script_history"]
                logger.info(f"✅ Added script_history to message")
        
        # If we still don't have a script but have script_history, extract from it
        if not latest_message.get("script") and result.get("script_history"):
            script_history = result["script_history"]
            if script_history and len(script_history) > 0:
                # Get the latest script from history
                latest_script_version = script_history[-1]
                if latest_script_version.get("script"):
                    latest_message["script"] = latest_script_version["script"]
                    logger.info(f"✅ Added script from script_history to message")
        
        # Validate script structure before returning
        if latest_message.get("script"):
            script = latest_message["script"]
            # Ensure required fields exist with defaults
            if not isinstance(script, dict):
                logger.warning(f"⚠️ Script is not a dict, converting...")
                script = {"title": "Script", "hook": "", "scenes": [], "call_to_action": "", "hashtags": []}
                latest_message["script"] = script
            
            # Ensure scenes is an array
            if "scenes" not in script or not isinstance(script.get("scenes"), list):
                script["scenes"] = []
            
            # Ensure hashtags is an array
            if "hashtags" not in script or not isinstance(script.get("hashtags"), list):
                script["hashtags"] = []
            
            # Ensure all scene objects have proper structure
            for scene in script.get("scenes", []):
                if not isinstance(scene, dict):
                    continue
                # Ensure all scene fields are strings
                for key in ["duration", "visual", "audio", "on_screen_text"]:
                    if key in scene and not isinstance(scene[key], str):
                        scene[key] = str(scene[key]) if scene[key] is not None else ""
            
            logger.info(f"✅ Script structure validated. Keys: {list(script.keys())}, Scenes: {len(script.get('scenes', []))}")
        
        # Log final message structure
        if latest_message.get("script"):
            logger.info(f"✅ Returning message with script. Script keys: {list(latest_message['script'].keys()) if isinstance(latest_message['script'], dict) else 'not a dict'}")
            if latest_message.get("all_scripts"):
                logger.info(f"✅ Returning message with {len(latest_message['all_scripts'])} scripts in all_scripts")
        else:
            # This is normal for non-video content types (Image Post, Text Post, etc.)
            content_type = result.get("selected_content_type", "")
            if content_type and content_type.lower() not in ["reel", "shorts", "video"]:
                logger.debug(f"ℹ️ Returning message without script (normal for {content_type})")
            else:
                logger.debug(f"ℹ️ Returning message without script")
        
        return {
            "conversation_id": conversation_id,
            "message": latest_message,
            "current_step": result["current_step"],
            "progress_percentage": result.get("progress_percentage", 0),
            "state": {
                "selected_platform": result.get("selected_platform"),
                "selected_content_type": result.get("selected_content_type"),
                "has_media": result.get("has_media"),
                "media_type": result.get("media_type"),
                "is_complete": result.get("is_complete", False),
                "error_message": result.get("error_message"),
                "script_id": result.get("script_id"),  # Include script_id in state
                # Carousel-related fields
                "carousel_images": result.get("carousel_images"),
                "carousel_image_source": result.get("carousel_image_source"),
                "current_carousel_index": result.get("current_carousel_index", 0),
                "carousel_max_images": result.get("carousel_max_images", 10),
                "uploaded_carousel_images": result.get("uploaded_carousel_images"),
                "carousel_upload_done": result.get("carousel_upload_done", False),
                "carousel_theme": result.get("carousel_theme")
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing user input: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process input: {str(e)}")

@router.post("/upload-media")
async def upload_media(
    conversation_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload media file for the conversation using LangGraph"""
    try:
        logger.info(f"Upload request received: conversation_id={conversation_id}, filename={file.filename}, content_type={file.content_type}")
        
        # Validate file exists
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        # Get conversation state
        if conversation_id not in conversation_states:
            logger.error(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found. Please refresh and try again.")
        
        state = conversation_states[conversation_id]
        logger.info(f"Found conversation state for user: {state.get('user_id')}")
        
        # Validate file size (100MB limit for videos, 10MB for images)
        MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
        MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10MB
        
        # Read file content with size check
        file_content = await file.read()
        file_size = len(file_content)
        logger.info(f"Read file content: {file_size} bytes")
        
        # Check if it's a video or image
        is_video = file.content_type and file.content_type.startswith('video/')
        max_size = MAX_VIDEO_SIZE if is_video else MAX_IMAGE_SIZE
        size_limit_mb = 100 if is_video else 10
        
        if file_size > max_size:
            raise HTTPException(
                status_code=400, 
                detail=f"File size ({file_size / (1024*1024):.1f}MB) exceeds the maximum allowed size of {size_limit_mb}MB for {'videos' if is_video else 'images'}"
            )
        
        if file_size == 0:
            raise HTTPException(status_code=400, detail="File is empty")
        
        # Upload media using the agent
        updated_state = await custom_content_agent.upload_media(
            state, file_content, file.filename, file.content_type
        )
        logger.info(f"Media upload completed, new step: {updated_state.get('current_step')}")
        
        # Check for errors in the upload state
        if updated_state.get("error_message"):
            logger.error(f"Upload error in state: {updated_state.get('error_message')}")
            raise HTTPException(status_code=500, detail=updated_state.get("error_message"))
        
        # Execute the conversation step using LangGraph
        result = await custom_content_agent.execute_conversation_step(updated_state)
        
        # Update conversation state
        conversation_states[conversation_id] = result
        
        # Get the last message
        last_message = result["conversation_messages"][-1] if result["conversation_messages"] else {
            "role": "assistant",
            "content": "Media uploaded successfully",
            "timestamp": datetime.now().isoformat()
        }
        
        response_data = {
            "conversation_id": conversation_id,
            "message": last_message,
            "current_step": result["current_step"],
            "progress_percentage": result.get("progress_percentage", 0),
            "media_url": result.get("uploaded_media_url"),
            "media_filename": result.get("uploaded_media_filename"),
            "media_size": result.get("uploaded_media_size"),
            "media_type": result.get("uploaded_media_type"),
            "state": {
                "selected_platform": result.get("selected_platform"),
                "selected_content_type": result.get("selected_content_type"),
                "has_media": result.get("has_media"),
                "media_type": result.get("media_type"),
                "is_complete": result.get("is_complete", False),
                "error_message": result.get("error_message")
            }
        }
        
        logger.info(f"Media upload response prepared: {result['current_step']}")
        return response_data
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error uploading media: {e}", exc_info=True)
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Traceback: {error_traceback}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to upload media. Please check the file size and format, then try again. Error: {str(e)}"
        )

@router.post("/generate-all-carousel-images")
async def generate_all_carousel_images(
    conversation_id: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Generate all 4 carousel images at once"""
    try:
        logger.info(f"generate-all-carousel-images endpoint called for conversation: {conversation_id}")
        if conversation_id not in conversation_states:
            logger.error(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        # Verify it's a carousel post
        if state.get("selected_content_type", "").lower() != "carousel":
            raise HTTPException(status_code=400, detail="This conversation is not for a carousel post")
        
        # Generate image using media agent
        from agents.media_agent import create_media_agent
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if not gemini_api_key:
            raise HTTPException(status_code=500, detail="Image generation not available - GEMINI_API_KEY not set")
        
        media_agent = create_media_agent(supabase_url, supabase_service_key, gemini_api_key)
        
        # Build description for carousel images
        user_description = state.get("user_description", "Carousel post")
        platform = state.get("selected_platform", "Facebook")
        business_context = state.get("business_context") or {}
        carousel_theme = state.get("carousel_theme", f"Sequential carousel story about: {user_description}")
        
        # Validate required fields
        user_id = state.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found in conversation state")
        
        # Generate all 4 images sequentially
        generated_images = []
        previous_prompts = []
        
        for image_index in range(4):
            # Create sequential, related description for each image
            if image_index == 0:
                image_description = f"{carousel_theme} - Image 1 of 4: Opening/Introduction scene. This is the first image in a 4-part sequential carousel story that will tell a cohesive narrative."
            elif image_index == 1:
                image_description = f"{carousel_theme} - Image 2 of 4: Development/Building scene. This is the second image in a 4-part sequential carousel story, building on the first image. The style, color palette, and theme must match the previous image to maintain visual consistency."
            elif image_index == 2:
                image_description = f"{carousel_theme} - Image 3 of 4: Peak/Climax scene. This is the third image in a 4-part sequential carousel story, continuing the narrative from the previous images. Maintain visual consistency, color palette, and story progression."
            else:  # image_index == 3
                image_description = f"{carousel_theme} - Image 4 of 4: Conclusion/Call to action scene. This is the final image in a 4-part sequential carousel story, concluding the narrative. Must visually connect to and complete the story from all previous images with consistent style and colors."
            
            # Add business context
            business_name = ""
            if isinstance(business_context, dict):
                business_name = business_context.get("business_name", "")
            if business_name:
                image_description += f" for {business_name}"
            
            # Add context about previous images for sequential coherence
            if previous_prompts:
                image_description += f" Previous images in this carousel sequence: {', '.join(previous_prompts[:2])}. Ensure visual consistency, color palette, and narrative flow."
            
            # Generate image
            from agents.media_agent import MediaAgentState
            image_state = MediaAgentState(
                user_id=user_id,
                post_id=conversation_id,
                post_data={
                    "content": image_description,
                    "platform": platform.lower() if platform else "facebook",
                    "user_description": user_description,
                    "carousel_index": image_index,
                    "total_carousel_images": 4,
                    "previous_carousel_prompts": previous_prompts,
                    "is_sequential_carousel": True,
                    "carousel_theme": carousel_theme
                },
                image_prompt=None,
                image_style=None,
                image_size=None,
                generated_image_url=None,
                generation_cost=None,
                generation_time=None,
                generation_model=None,
                generation_service=None,
                error_message=None,
                status="pending"
            )
            
            try:
                logger.info(f"Generating carousel image {image_index + 1}/4 for conversation {conversation_id}")
                
                image_state = await media_agent.generate_image_prompt(image_state)
                if not image_state:
                    raise HTTPException(status_code=500, detail=f"Failed to generate image prompt for image {image_index + 1}")
                
                result = await media_agent.generate_image(image_state)
                if not result or not isinstance(result, dict):
                    raise HTTPException(status_code=500, detail=f"Failed to generate image {image_index + 1}")
                
                if result.get("status") != "completed" or not result.get("generated_image_url"):
                    error_msg = result.get("error_message", "Unknown error")
                    raise HTTPException(status_code=500, detail=f"Failed to generate image {image_index + 1}: {error_msg}")
                
                image_url = result.get("generated_image_url")
                image_prompt = image_state.get("image_prompt", "") if isinstance(image_state, dict) else ""
                
                generated_images.append({
                    "url": image_url,
                    "index": image_index,
                    "prompt": image_prompt,
                    "approved": False
                })
                
                previous_prompts.append(image_prompt)
                logger.info(f"Successfully generated carousel image {image_index + 1}/4")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error generating carousel image {image_index + 1}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to generate carousel image {image_index + 1}: {str(e)}")
        
        # Update state with all generated images
        state["carousel_images"] = generated_images
        state["current_step"] = ConversationStep.APPROVE_CAROUSEL_IMAGES
        conversation_states[conversation_id] = state
        
        # Trigger the approve_carousel_images step to add the approval message
        result = await custom_content_agent.approve_carousel_images(state, user_input=None)
        conversation_states[conversation_id] = result
        
        return {
            "success": True,
            "images": generated_images,
            "total_images": len(generated_images),
            "message": "All 4 carousel images generated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating all carousel images: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate carousel images: {str(e)}")

@router.post("/generate-carousel-image")
async def generate_carousel_image(
    conversation_id: str = Form(...),
    image_index: int = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Generate a single carousel image using AI (kept for backward compatibility)"""
    try:
        if conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        # Verify it's a carousel post
        if state.get("selected_content_type", "").lower() != "carousel":
            raise HTTPException(status_code=400, detail="This conversation is not for a carousel post")
        
        # Verify image index is valid (0-3)
        if image_index < 0 or image_index >= 4:
            raise HTTPException(status_code=400, detail="Image index must be between 0 and 3")
        
        # Generate image using media agent
        from agents.media_agent import create_media_agent
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if not gemini_api_key:
            raise HTTPException(status_code=500, detail="Image generation not available - GEMINI_API_KEY not set")
        
        media_agent = create_media_agent(supabase_url, supabase_service_key, gemini_api_key)
        
        # Build description for this specific carousel image
        user_description = state.get("user_description", "Carousel post")
        platform = state.get("selected_platform", "Facebook")
        business_context = state.get("business_context") or {}  # Ensure it's always a dict, not None
        carousel_images = state.get("carousel_images", []) or []  # Ensure it's always a list
        carousel_theme = state.get("carousel_theme", f"Sequential carousel story about: {user_description}")
        
        # Get previous images' prompts to maintain sequential relationship
        previous_prompts = []
        if carousel_images:
            for img in carousel_images:
                if isinstance(img, dict) and img.get("prompt"):
                    previous_prompts.append(img.get("prompt"))
        
        # Create sequential, related description for each image in carousel
        # Each image should build on the previous ones to tell a cohesive story
        if image_index == 0:
            # First image: Introduction/Opening
            image_description = f"{carousel_theme} - Image 1 of 4: Opening/Introduction scene. This is the first image in a 4-part sequential carousel story that will tell a cohesive narrative."
        elif image_index == 1:
            # Second image: Development/Building
            image_description = f"{carousel_theme} - Image 2 of 4: Development/Building scene. This is the second image in a 4-part sequential carousel story, building on the first image. The style, color palette, and theme must match the previous image to maintain visual consistency."
        elif image_index == 2:
            # Third image: Peak/Climax
            image_description = f"{carousel_theme} - Image 3 of 4: Peak/Climax scene. This is the third image in a 4-part sequential carousel story, continuing the narrative from the previous images. Maintain visual consistency, color palette, and story progression."
        else:  # image_index == 3
            # Fourth image: Conclusion/Call to action
            image_description = f"{carousel_theme} - Image 4 of 4: Conclusion/Call to action scene. This is the final image in a 4-part sequential carousel story, concluding the narrative. Must visually connect to and complete the story from all previous images with consistent style and colors."
        
        # Add business context (safely handle None)
        business_name = ""
        if isinstance(business_context, dict):
            business_name = business_context.get("business_name", "")
        if business_name:
            image_description += f" for {business_name}"
        
        # Add context about previous images for sequential coherence
        if previous_prompts:
            image_description += f" Previous images in this carousel sequence: {', '.join(previous_prompts[:2])}. Ensure visual consistency, color palette, and narrative flow."
        
        # Validate required fields
        user_id = state.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found in conversation state")
        
        # Generate image
        from agents.media_agent import MediaAgentState
        image_state = MediaAgentState(
            user_id=user_id,
            post_id=conversation_id,
            post_data={
                "content": image_description,
                "platform": platform.lower() if platform else "facebook",
                "user_description": user_description,
                "carousel_index": image_index,
                "total_carousel_images": 4,
                "previous_carousel_prompts": previous_prompts,
                "is_sequential_carousel": True,
                "carousel_theme": carousel_theme
            },
            image_prompt=None,
            image_style=None,
            image_size=None,
            generated_image_url=None,
            generation_cost=None,
            generation_time=None,
            generation_model=None,
            generation_service=None,
            error_message=None,
            status="pending"
        )
        
        # Generate prompt and image
        try:
            logger.info(f"Generating carousel image {image_index + 1} for conversation {conversation_id}")
            logger.info(f"Image description: {image_description[:200]}...")
            
            image_state = await media_agent.generate_image_prompt(image_state)
            if not image_state:
                logger.error("generate_image_prompt returned None")
                raise HTTPException(status_code=500, detail="Failed to generate image prompt - media agent returned None")
            
            logger.info(f"Image prompt generated: {image_state.get('image_prompt', 'N/A')[:100]}...")
            
            result = await media_agent.generate_image(image_state)
            if not result:
                logger.error("generate_image returned None")
                raise HTTPException(status_code=500, detail="Failed to generate image - media agent returned None")
            
            logger.info(f"Image generation result status: {result.get('status', 'N/A')}")
            
            # Ensure result is a dict-like object
            if not isinstance(result, dict):
                raise HTTPException(status_code=500, detail=f"Unexpected result type from media agent: {type(result)}")
            
            if result.get("status") != "completed" or not result.get("generated_image_url"):
                error_msg = result.get("error_message", "Unknown error")
                raise HTTPException(status_code=500, detail=f"Failed to generate image: {error_msg}")
            
            image_url = result.get("generated_image_url")
            if not image_url:
                raise HTTPException(status_code=500, detail="Image generation completed but no image URL returned")
            
            # Add to carousel images list (ensure it's initialized)
            carousel_images = state.get("carousel_images") or []
            if not isinstance(carousel_images, list):
                carousel_images = []
            
            # Safely get image prompt
            image_prompt = ""
            if isinstance(image_state, dict):
                image_prompt = image_state.get("image_prompt", "")
            
            carousel_images.append({
                "url": image_url,
                "index": image_index,
                "prompt": image_prompt,
                "approved": False
            })
            state["carousel_images"] = carousel_images
            conversation_states[conversation_id] = state
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in carousel image generation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to generate carousel image: {str(e)}")
        
        return {
            "success": True,
            "image_url": image_url,
            "image_index": image_index,
            "total_images": len(carousel_images),
            "max_images": 4
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating carousel image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate carousel image: {str(e)}")

@router.post("/upload-carousel-images")
async def upload_carousel_images(
    conversation_id: str = Form(...),
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload multiple carousel images"""
    try:
        logger.info(f"upload-carousel-images endpoint called for conversation: {conversation_id}, files: {len(files)}")
        if conversation_id not in conversation_states:
            logger.error(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        # Verify it's a carousel post
        if state.get("selected_content_type", "").lower() != "carousel":
            raise HTTPException(status_code=400, detail="This conversation is not for a carousel post")
        
        max_images = state.get("carousel_max_images", 10)
        # CRITICAL: Get existing uploaded images BEFORE the loop to preserve them
        current_uploaded = state.get("uploaded_carousel_images") or []
        if not isinstance(current_uploaded, list):
            current_uploaded = []
        current_count = len(current_uploaded)
        
        # Check if adding these files would exceed max
        if current_count + len(files) > max_images:
            raise HTTPException(
                status_code=400, 
                detail=f"Uploading {len(files)} images would exceed the maximum of {max_images} images. You can upload up to {max_images - current_count} more images."
            )
        
        # Validate file sizes (10MB per image)
        MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
        
        uploaded_urls = []
        for file in files:
            if not file.filename:
                continue
            
            # Read file content
            file_content = await file.read()
            file_size = len(file_content)
            
            if file_size > MAX_IMAGE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"File {file.filename} exceeds the maximum size of 10MB"
                )
            
            if file_size == 0:
                continue
            
            # Upload media using the agent
            updated_state = await custom_content_agent.upload_media(
                state, file_content, file.filename, file.content_type
            )
            
            # Get the uploaded URL
            uploaded_url = updated_state.get("uploaded_media_url")
            if uploaded_url:
                uploaded_urls.append(uploaded_url)
            
            # Preserve uploaded_carousel_images from original state
            # upload_media might not preserve it, so we maintain it separately
            if "uploaded_carousel_images" not in updated_state or not updated_state.get("uploaded_carousel_images"):
                updated_state["uploaded_carousel_images"] = current_uploaded.copy()
            
            # Update state with the returned state
            state = updated_state
        
        # CRITICAL: Append new images to existing list (don't replace)
        # This ensures images accumulate across multiple uploads
        current_uploaded.extend(uploaded_urls)
        state["uploaded_carousel_images"] = current_uploaded
        conversation_states[conversation_id] = state
        
        logger.info(f"✅ Carousel images updated: {len(current_uploaded)} total (added {len(uploaded_urls)} new)")
        
        # Check if we should ask if done
        new_count = len(current_uploaded)
        if new_count >= max_images:
            # At max, proceed to done confirmation
            state["current_step"] = ConversationStep.CONFIRM_CAROUSEL_UPLOAD_DONE
        else:
            # Not at max, ask if done
            state["current_step"] = ConversationStep.CONFIRM_CAROUSEL_UPLOAD_DONE
        
        conversation_states[conversation_id] = state
        
        return {
            "success": True,
            "uploaded_count": len(uploaded_urls),
            "total_images": new_count,
            "max_images": max_images,
            "image_urls": uploaded_urls
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading carousel images: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload carousel images: {str(e)}")

@router.get("/conversation/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get conversation state and messages"""
    try:
        if conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        return {
            "conversation_id": conversation_id,
            "messages": state["conversation_messages"],
            "current_step": state["current_step"],
            "progress_percentage": state["progress_percentage"],
            "state": {
                "selected_platform": state.get("selected_platform"),
                "selected_content_type": state.get("selected_content_type"),
                "has_media": state.get("has_media"),
                "media_type": state.get("media_type"),
                "is_complete": state.get("is_complete"),
                "final_post": state.get("final_post"),
                "carousel_images": state.get("carousel_images"),
                "carousel_image_source": state.get("carousel_image_source"),
                "current_carousel_index": state.get("current_carousel_index", 0),
                "carousel_max_images": state.get("carousel_max_images", 10),
                "uploaded_carousel_images": state.get("uploaded_carousel_images"),
                "carousel_upload_done": state.get("carousel_upload_done", False),
                "carousel_theme": state.get("carousel_theme")
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get conversation: {str(e)}")

@router.post("/conversation/{conversation_id}/continue")
async def continue_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Continue the conversation flow from current step"""
    try:
        if conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[conversation_id]
        
        # Use execute_conversation_step instead of graph directly
        # This ensures proper handling of CONFIRM_SCRIPT and other steps
        result = await custom_content_agent.execute_conversation_step(state)
        conversation_states[conversation_id] = result
        
        return {
            "conversation_id": conversation_id,
            "message": result["conversation_messages"][-1],
            "current_step": result["current_step"],
            "progress_percentage": result["progress_percentage"],
            "state": {
                "selected_platform": result.get("selected_platform"),
                "selected_content_type": result.get("selected_content_type"),
                "has_media": result.get("has_media"),
                "media_type": result.get("media_type"),
                "is_complete": result.get("is_complete"),
                "final_post": result.get("final_post")
            }
        }
        
    except Exception as e:
        logger.error(f"Error continuing conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to continue conversation: {str(e)}")

@router.delete("/conversation/{conversation_id}")
async def end_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """End and clean up a conversation"""
    try:
        if conversation_id in conversation_states:
            del conversation_states[conversation_id]
            return {"message": "Conversation ended successfully"}
        else:
            raise HTTPException(status_code=404, detail="Conversation not found")
            
    except Exception as e:
        logger.error(f"Error ending conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to end conversation: {str(e)}")

@router.get("/platforms/{user_id}")
async def get_user_platforms(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get user's connected platforms for content creation"""
    try:
        # This would typically fetch from the database
        # For now, return a mock response
        return {
            "platforms": ["Facebook", "Instagram", "LinkedIn", "Twitter/X", "TikTok"]
        }
        
    except Exception as e:
        logger.error(f"Error getting user platforms: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get platforms: {str(e)}")

@router.get("/content-types/{platform}")
async def get_content_types(platform: str):
    """Get available content types for a platform"""
    try:
        from agents.custom_content_agent import PLATFORM_CONTENT_TYPES
        
        content_types = PLATFORM_CONTENT_TYPES.get(platform, [])
        
        return {
            "platform": platform,
            "content_types": content_types
        }
        
    except Exception as e:
        logger.error(f"Error getting content types: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get content types: {str(e)}")

@router.get("/media-requirements/{platform}")
async def get_media_requirements(platform: str):
    """Get media requirements for a platform"""
    try:
        from agents.custom_content_agent import PLATFORM_MEDIA_REQUIREMENTS
        
        requirements = PLATFORM_MEDIA_REQUIREMENTS.get(platform, {})
        
        return {
            "platform": platform,
            "requirements": requirements
        }
        
    except Exception as e:
        logger.error(f"Error getting media requirements: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get media requirements: {str(e)}")

class SaveDraftRequest(BaseModel):
    conversation_id: str
    script_id: Optional[str] = None
    script_version: Optional[int] = None  # Which script version to save (from script_history)
    
    @field_validator('script_id', mode='before')
    @classmethod
    def convert_script_id_to_string(cls, v):
        """Convert script_id to string if it's a number, or None if it's null/empty"""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return v if v.strip() else None
        return str(v) if v else None

@router.post("/save-script-draft")
async def save_script_draft(
    request: SaveDraftRequest,
    current_user: dict = Depends(get_current_user)
):
    """Save script as draft to content_posts table in the video_scripting column."""
    try:
        if request.conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[request.conversation_id]
        
        # Get script data from state
        # If script_version is specified, get that version from script_history
        script_data = None
        script_history = state.get("script_history", [])
        
        if request.script_version and script_history:
            # Find the specific version
            for script_version in script_history:
                if script_version.get("version") == request.script_version:
                    script_data = script_version.get("script")
                    logger.info(f"✅ Using script version {request.script_version} from cache")
                    break
        
        # If no version specified or version not found, use current script
        if not script_data:
            script_data = state.get("generated_script")
        
        # If still not found, try to get from latest message
        if not script_data:
            messages = state.get("conversation_messages", [])
            for msg in reversed(messages):
                if msg.get("script"):
                    script_data = msg.get("script")
                    break
        
        if not script_data:
            raise HTTPException(status_code=400, detail="Script data not found")
        
        # Get metadata from state
        platform = state.get("selected_platform", "instagram")
        content_type = state.get("selected_content_type", "reel")
        user_description = state.get("user_description")
        clarification_1 = state.get("clarification_1")
        clarification_2 = state.get("clarification_2")
        clarification_3 = state.get("clarification_3")
        business_context = state.get("business_context", {})
        
        # Ensure business_context is a dict (not None or other type)
        if business_context is None:
            business_context = {}
        elif not isinstance(business_context, dict):
            # If it's not a dict, try to convert it or use empty dict
            try:
                if hasattr(business_context, '__dict__'):
                    business_context = business_context.__dict__
                else:
                    business_context = {}
            except:
                business_context = {}
        
        # Ensure script_data is a dict
        if not isinstance(script_data, dict):
            raise HTTPException(status_code=400, detail="Script data must be a valid object")
        
        # Clean script_data and business_context to ensure all values are JSON serializable
        try:
            cleaned_script_data = clean_for_json(script_data)
            business_context = clean_for_json(business_context)
            # Test serialization to catch any issues early
            json.dumps(cleaned_script_data)
            json.dumps(business_context)
            logger.info("✅ Script data and business_context validated for JSON serialization")
        except (TypeError, ValueError) as e:
            logger.error(f"JSON serialization error: {e}")
            raise HTTPException(status_code=400, detail=f"Script data contains non-serializable values: {str(e)}")
        
        # Use cleaned script data for all database operations
        script_data = cleaned_script_data
        
        # Save or update script in content_posts table
        # If script_post_id exists, UPDATE it with the latest script from memory
        # Otherwise, create a new record
        from datetime import date, timedelta
        script_post_id = state.get("script_id")
        
        # Create a temporary campaign for this custom content if it doesn't exist
        campaign_id = state.get("campaign_id")
        if not campaign_id:
            today = date.today()
            campaign_data = {
                "user_id": state["user_id"],
                "campaign_name": f"Custom {content_type} - {today.strftime('%Y-%m-%d')}",
                "week_start_date": today.isoformat(),
                "week_end_date": (today + timedelta(days=7)).isoformat(),
                "status": "draft"
            }
            campaign_result = custom_content_agent.supabase.table("content_campaigns").insert(campaign_data).execute()
            campaign_id = campaign_result.data[0]["id"] if campaign_result.data else None
            state["campaign_id"] = campaign_id
        
        # Prepare script data for database
        # Ensure all values are properly serializable
        post_data = {
            "campaign_id": campaign_id,
            "platform": str(platform) if platform else "instagram",
            "post_type": str(content_type.lower()) if content_type else "reel",
            "title": str(script_data.get('title', f"{content_type} Script")),
            "content": str(user_description or script_data.get('hook', '')),
            "hashtags": list(script_data.get('hashtags', [])) if script_data.get('hashtags') else [],
            "scheduled_date": date.today().isoformat(),
            "scheduled_time": "12:00:00",
            "status": "draft",
            "video_scripting": script_data,  # Already cleaned above - JSONB field
            "metadata": {
                "user_description": str(user_description) if user_description else "",
                "clarification_1": str(clarification_1) if clarification_1 else "",
                "clarification_2": str(clarification_2) if clarification_2 else "",
                "clarification_3": str(clarification_3) if clarification_3 else "",
                "business_context": business_context  # Already validated as dict above
            }
        }
        
        if script_post_id:
            # Update existing script record with the latest script from memory
            result = custom_content_agent.supabase.table("content_posts").update(post_data).eq("id", script_post_id).execute()
            logger.info(f"✅ Updated existing script in content_posts table with ID: {script_post_id}")
        else:
            # Create new script record (first time saving)
            result = custom_content_agent.supabase.table("content_posts").insert(post_data).execute()
            script_post_id = result.data[0]["id"] if result.data else None
            state["script_id"] = script_post_id
            state["script_post_id"] = script_post_id
            logger.info(f"✅ Script saved to content_posts table with ID: {script_post_id}")
        
        # Update state with script_post_id
        conversation_states[request.conversation_id] = state
        
        # Script is already saved in content_posts table above with video_scripting column
        # Verify the script was saved correctly in content_posts table
        try:
            if script_post_id:
                verify_result = custom_content_agent.supabase.table("content_posts")\
                    .select("*")\
                    .eq("id", script_post_id)\
                    .execute()
                
                if verify_result.data and verify_result.data[0]:
                    saved_script = verify_result.data[0].get("video_scripting")
                    if saved_script:
                        logger.info(f"✅ Verified script saved correctly in content_posts. Script keys: {list(saved_script.keys()) if isinstance(saved_script, dict) else 'not a dict'}")
                    else:
                        logger.warning(f"⚠️ Script saved but video_scripting column is empty for {script_post_id}")
                else:
                    logger.warning(f"⚠️ Could not verify saved script {script_post_id}")
            else:
                logger.warning("⚠️ No script_post_id to verify")
        except Exception as verify_error:
            logger.warning(f"⚠️ Error verifying saved script: {verify_error}")
        
        # Return the script_post_id as draft_id for consistency
        return {
            "success": True,
            "draft_id": str(script_post_id) if script_post_id else None,
            "script_post_id": str(script_post_id) if script_post_id else None,
            "message": "Script saved as draft successfully in content_posts table",
            "script": script_data  # Return the script data that was saved
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving script draft: {e}", exc_info=True)
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Traceback: {error_traceback}")
        # Ensure error message is a string, not an object
        error_message = str(e) if e else "Unknown error occurred"
        raise HTTPException(status_code=500, detail=error_message)

@router.get("/saved-scripts")
async def get_saved_scripts(
    current_user: dict = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0
):
    """Get all saved scripts from content_posts table (video_scripting column) for the current user"""
    try:
        user_id = str(current_user["sub"])
        
        # Fetch scripts from content_posts table where video_scripting is not null
        # Join with content_campaigns to filter by user_id
        result = custom_content_agent.supabase.table("content_posts")\
            .select("*, content_campaigns!inner(user_id)")\
            .eq("content_campaigns.user_id", user_id)\
            .not_.is_("video_scripting", "null")\
            .order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        if not result.data:
            return {
                "scripts": [],
                "count": 0,
                "limit": limit,
                "offset": offset
            }
        
        # Format scripts for response
        scripts = []
        for script_record in result.data:
            # Get metadata for additional info
            metadata = script_record.get("metadata", {})
            script_data = {
                "id": script_record.get("id"),
                "draft_id": script_record.get("id"),  # Alias for consistency
                "platform": script_record.get("platform"),
                "content_type": script_record.get("post_type"),
                "script": script_record.get("video_scripting"),  # The actual script data from video_scripting column
                "user_description": metadata.get("user_description", ""),
                "clarification_1": metadata.get("clarification_1", ""),
                "clarification_2": metadata.get("clarification_2", ""),
                "clarification_3": metadata.get("clarification_3", ""),
                "business_context": metadata.get("business_context", {}),
                "status": script_record.get("status", "draft"),
                "created_at": script_record.get("created_at"),
                "updated_at": script_record.get("updated_at")
            }
            scripts.append(script_data)
        
        logger.info(f"✅ Retrieved {len(scripts)} saved scripts for user {user_id}")
        
        return {
            "scripts": scripts,
            "count": len(scripts),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"Error retrieving saved scripts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve saved scripts: {str(e)}")

@router.get("/saved-script/{draft_id}")
async def get_saved_script(
    draft_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific saved script by draft_id from content_posts table (video_scripting column)"""
    try:
        user_id = str(current_user["sub"])
        
        # Fetch script from content_posts table
        # Join with content_campaigns to verify user ownership
        result = custom_content_agent.supabase.table("content_posts")\
            .select("*, content_campaigns!inner(user_id)")\
            .eq("id", draft_id)\
            .eq("content_campaigns.user_id", user_id)\
            .execute()
        
        if not result.data or len(result.data) == 0:
            raise HTTPException(status_code=404, detail="Script not found")
        
        script_record = result.data[0]
        
        # Get metadata for additional info
        metadata = script_record.get("metadata", {})
        
        # Format script for response
        script_data = {
            "id": script_record.get("id"),
            "draft_id": script_record.get("id"),
            "platform": script_record.get("platform"),
            "content_type": script_record.get("post_type"),
            "script": script_record.get("video_scripting"),  # The actual script data from video_scripting column
            "user_description": metadata.get("user_description", ""),
            "clarification_1": metadata.get("clarification_1", ""),
            "clarification_2": metadata.get("clarification_2", ""),
            "clarification_3": metadata.get("clarification_3", ""),
            "business_context": metadata.get("business_context", {}),
            "status": script_record.get("status", "draft"),
            "created_at": script_record.get("created_at"),
            "updated_at": script_record.get("updated_at")
        }
        
        logger.info(f"✅ Retrieved script {draft_id} for user {user_id}")
        
        return {
            "success": True,
            "script": script_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving script {draft_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve script: {str(e)}")

class RegenerateScriptRequest(BaseModel):
    conversation_id: str
    changes: str  # User's requested changes/modifications

@router.post("/regenerate-script")
async def regenerate_script(
    request: RegenerateScriptRequest,
    current_user: dict = Depends(get_current_user)
):
    """Regenerate the script with user-specified changes"""
    try:
        if request.conversation_id not in conversation_states:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        state = conversation_states[request.conversation_id]
        
        # Check if we have the necessary data to regenerate
        if not state.get("selected_platform") or not state.get("selected_content_type"):
            raise HTTPException(status_code=400, detail="Platform and content type are required to regenerate script")
        
        # Check if we have a previous script
        if not state.get("generated_script"):
            raise HTTPException(status_code=400, detail="No previous script found to regenerate")
        
        # Validate changes input
        if not request.changes or not request.changes.strip():
            raise HTTPException(status_code=400, detail="Please provide the changes or modifications you'd like to make")
        
        # Call generate_script with changes parameter (this will keep all scripts in cache)
        result = await custom_content_agent.generate_script(state, changes=request.changes.strip())
        
        # Update conversation state
        conversation_states[request.conversation_id] = result
        
        # Get the latest message with all scripts
        latest_message = result["conversation_messages"][-1] if result["conversation_messages"] else None
        
        # Script is already in the message from generate_script with all scripts
        if latest_message and latest_message.get("script"):
            logger.info(f"✅ Regenerated script with changes: {request.changes[:50]}...")
            logger.info(f"📝 Total scripts in cache: {len(result.get('script_history', []))}")
        
        return {
            "success": True,
            "conversation_id": request.conversation_id,
            "message": latest_message,
            "current_step": result["current_step"],
            "progress_percentage": result.get("progress_percentage", 0),
            "script_history": result.get("script_history", [])  # Return all scripts
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to regenerate script: {str(e)}")

"""
Custom Content Creation Agent using LangGraph
Interactive chatbot for creating custom social media content
Supports image and video uploads with platform-specific optimization
"""

import json
import asyncio
import logging
import base64
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, TypedDict, Union
from dataclasses import dataclass
from enum import Enum

import openai
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from supabase import create_client, Client
import httpx
import os
from dotenv import load_dotenv

# Import media agent
from .media_agent import create_media_agent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Initialize OpenAI
openai_api_key = os.getenv("OPENAI_API_KEY")

class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    NONE = "none"

class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    CAROUSEL = "carousel"
    STORY = "story"
    REEL = "reel"
    LIVE = "live"
    POLL = "poll"
    QUESTION = "question"
    ARTICLE = "article"
    THREAD = "thread"
    PIN = "pin"
    SHORT = "short"

class ConversationStep(str, Enum):
    GREET = "greet"
    ASK_PLATFORM = "ask_platform"
    ASK_CONTENT_TYPE = "ask_content_type"
    ASK_DESCRIPTION = "ask_description"
    ASK_MEDIA = "ask_media"
    HANDLE_MEDIA = "handle_media"
    VALIDATE_MEDIA = "validate_media"
    CONFIRM_MEDIA = "confirm_media"
    EDIT_IMAGE = "edit_image"
    ASK_THUMBNAIL = "ask_thumbnail"
    ASK_CAROUSEL_IMAGE_SOURCE = "ask_carousel_image_source"
    GENERATE_CAROUSEL_IMAGE = "generate_carousel_image"
    APPROVE_CAROUSEL_IMAGES = "approve_carousel_images"
    HANDLE_CAROUSEL_UPLOAD = "handle_carousel_upload"
    CONFIRM_CAROUSEL_UPLOAD_DONE = "confirm_carousel_upload_done"
    GENERATE_SCRIPT = "generate_script"
    CONFIRM_SCRIPT = "confirm_script"
    GENERATE_CONTENT = "generate_content"
    PREVIEW_AND_EDIT = "preview_and_edit"
    CONFIRM_CONTENT = "confirm_content"
    SELECT_SCHEDULE = "select_schedule"
    SAVE_CONTENT = "save_content"
    ASK_ANOTHER_CONTENT = "ask_another_content"
    DISPLAY_RESULT = "display_result"
    ERROR = "error"

class CustomContentState(TypedDict):
    """State for the custom content creation conversation"""
    user_id: str
    conversation_id: Optional[str]
    conversation_messages: List[Dict[str, str]]  # Chat history
    current_step: ConversationStep
    selected_platform: Optional[str]
    selected_content_type: Optional[str]
    user_description: Optional[str]
    clarification_1: Optional[str]
    clarification_2: Optional[str]
    clarification_3: Optional[str]
    has_media: Optional[bool]
    media_type: Optional[MediaType]
    uploaded_media_url: Optional[str]
    should_generate_media: Optional[bool]
    media_prompt: Optional[str]
    generated_content: Optional[Dict[str, Any]]
    generated_script: Optional[Dict[str, Any]]
    generated_media_url: Optional[str]
    final_post: Optional[Dict[str, Any]]
    error_message: Optional[str]
    platform_content_types: Optional[Dict[str, List[str]]]
    media_requirements: Optional[Dict[str, Any]]
    validation_errors: Optional[List[str]]
    retry_count: int
    is_complete: bool
    # Carousel-specific fields
    carousel_images: Optional[List[Dict[str, Any]]]  # List of carousel image objects
    carousel_image_source: Optional[str]  # "ai_generate" or "manual_upload"
    current_carousel_index: int  # Current image index (0-3 for AI, 0-max for manual)
    carousel_max_images: int  # Platform-specific max (10 for Facebook, 20 for Instagram)
    uploaded_carousel_images: Optional[List[str]]  # URLs of uploaded images
    carousel_upload_done: bool  # Whether user confirmed upload is complete
    carousel_theme: Optional[str]  # Overall theme/narrative for sequential carousel images
    # Preview and edit fields
    content_history: Optional[List[Dict[str, Any]]]  # History of content versions for undo
    current_content_version: int  # Current version index in content_history
    preview_confirmed: Optional[bool]  # Whether user confirmed preview
    wants_to_edit: Optional[bool]  # Whether user wants to edit
    edit_prompt: Optional[str]  # Natural language edit prompt from user
    edited_image_url: Optional[str]  # URL of the last edited image
    image_edit_type: Optional[str]  # Type of image edit performed
    use_image_as_is: Optional[bool]  # Flag if user wants to use image as is
    wants_to_edit_image: Optional[bool]  # Flag if user wants to edit image
    image_edit_prompt: Optional[str]  # User's natural language image edit prompt

# Platform-specific content types
PLATFORM_CONTENT_TYPES = {
    "Instagram": ["Image Post", "Reel", "Carousel"],
    "Facebook": ["Image Post", "Reel", "Text Post", "Carousel"],
    "YouTube": ["Shorts", "Video"],  # Community Post = manual only
    "LinkedIn": ["Image Post", "Video", "Text Post", "Carousel"],
    "Twitter/X": ["Image Post", "Video", "Text Post"],
    "Reddit": ["Image Post",  "Text Post"],  # No true carousel
    "Pinterest": ["Video", "Photo"]
}


# Platform-specific media requirements
PLATFORM_MEDIA_REQUIREMENTS = {
    "Facebook": {
        "image": {
            "sizes": ["1200x630", "1200x675", "1080x1080"],
            "formats": ["jpg", "png", "gif"],
            "max_size": "10MB"
        },
        "video": {
            "sizes": ["1280x720", "1920x1080", "1080x1080"],
            "formats": ["mp4", "mov", "avi"],
            "max_size": "4GB",
            "max_duration": "240 minutes"
        }
    },
    "Instagram": {
        "image": {
            "sizes": ["1080x1080", "1080x1350", "1080x566"],
            "formats": ["jpg", "png"],
            "max_size": "30MB"
        },
        "video": {
            "sizes": ["1080x1080", "1080x1350", "1080x1920"],
            "formats": ["mp4", "mov"],
            "max_size": "100MB",
            "max_duration": "60 seconds"
        }
    },
    "LinkedIn": {
        "image": {
            "sizes": ["1200x627", "1200x1200"],
            "formats": ["jpg", "png"],
            "max_size": "5MB"
        },
        "video": {
            "sizes": ["1280x720", "1920x1080"],
            "formats": ["mp4", "mov"],
            "max_size": "5GB",
            "max_duration": "10 minutes"
        }
    },
    "Twitter/X": {
        "image": {
            "sizes": ["1200x675", "1200x1200"],
            "formats": ["jpg", "png", "gif"],
            "max_size": "5MB"
        },
        "video": {
            "sizes": ["1280x720", "1920x1080"],
            "formats": ["mp4", "mov"],
            "max_size": "512MB",
            "max_duration": "2 minutes 20 seconds"
        }
    },
    "YouTube": {
        "image": {
            "sizes": ["1280x720", "1920x1080"],
            "formats": ["jpg", "png"],
            "max_size": "2MB"
        },
        "video": {
            "sizes": ["1280x720", "1920x1080", "3840x2160"],
            "formats": ["mp4", "mov", "avi"],
            "max_size": "256GB",
            "max_duration": "12 hours"
        }
    },
    "TikTok": {
        "image": {
            "sizes": ["1080x1920", "1080x1080"],
            "formats": ["jpg", "png"],
            "max_size": "10MB"
        },
        "video": {
            "sizes": ["1080x1920", "1080x1080"],
            "formats": ["mp4", "mov"],
            "max_size": "287MB",
            "max_duration": "3 minutes"
        }
    },
    "Pinterest": {
        "image": {
            "sizes": ["1000x1500", "1000x1000", "1000x2000"],
            "formats": ["jpg", "png"],
            "max_size": "32MB"
        },
        "video": {
            "sizes": ["1000x1500", "1000x1000"],
            "formats": ["mp4", "mov"],
            "max_size": "2GB",
            "max_duration": "15 minutes"
        }
    },
    "WhatsApp Business": {
        "image": {
            "sizes": ["any"],
            "formats": ["jpg", "png", "gif"],
            "max_size": "5MB"
        },
        "video": {
            "sizes": ["any"],
            "formats": ["mp4", "3gp"],
            "max_size": "16MB",
            "max_duration": "16 seconds"
        }
    }
}

class CustomContentAgent:
    """Custom Content Creation Agent using LangGraph"""
    
    def __init__(self, openai_api_key: str):
        self.openai_api_key = openai_api_key
        self.client = openai.OpenAI(api_key=openai_api_key)
        self.supabase = supabase
        
        # Initialize media agent
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_ANON_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if supabase_url and supabase_key and gemini_api_key:
            self.media_agent = create_media_agent(supabase_url, supabase_key, gemini_api_key)
        else:
            logger.warning("Media agent not initialized - missing environment variables")
            self.media_agent = None
        
    def create_graph(self) -> StateGraph:
        """Create the LangGraph workflow with proper conditional edges and state management"""
        graph = StateGraph(CustomContentState)
        
        # Add nodes
        graph.add_node("greet_user", self.greet_user)
        graph.add_node("ask_platform", self.ask_platform)
        graph.add_node("ask_content_type", self.ask_content_type)
        graph.add_node("ask_description", self.ask_description)
        graph.add_node("ask_media", self.ask_media)
        graph.add_node("handle_media", self.handle_media)
        graph.add_node("validate_media", self.validate_media)
        graph.add_node("confirm_media", self.confirm_media)
        graph.add_node("ask_thumbnail", self.ask_thumbnail)
        graph.add_node("generate_script", self.generate_script)
        graph.add_node("generate_content", self.generate_content)
        graph.add_node("edit_image", self.edit_image)
        graph.add_node("preview_and_edit", self.preview_and_edit)
        graph.add_node("confirm_content", self.confirm_content)
        graph.add_node("select_schedule", self.select_schedule)
        graph.add_node("save_content", self.save_content)
        graph.add_node("ask_another_content", self.ask_another_content)
        graph.add_node("display_result", self.display_result)
        graph.add_node("handle_error", self.handle_error)
        
        # Set entry point
        graph.set_entry_point("greet_user")
        
        # Linear flow for initial steps - each step waits for user input
        graph.add_edge("greet_user", "ask_platform")
        
        # Conditional edge for platform selection - loop back if not selected
        graph.add_conditional_edges(
            "ask_platform",
            self._should_proceed_from_platform,
            {
                "continue": "ask_content_type",
                "retry": "ask_platform"  # Loop back to same node on error
            }
        )
        
        # Conditional edge for content type selection - loop back if not selected
        graph.add_conditional_edges(
            "ask_content_type",
            self._should_proceed_from_content_type,
            {
                "continue": "ask_description",
                "retry": "ask_content_type"  # Loop back to same node on error
            }
        )
        
        graph.add_edge("ask_description", "ask_media")
        
        # Conditional edges for media handling
        graph.add_conditional_edges(
            "ask_media",
            self._should_handle_media,
            {
                "handle": "handle_media",
                "generate": "generate_content",
                "generate_script": "generate_script",
                "skip": "generate_content"
            }
        )
        
        # Script generation flow - after script is created, conditionally proceed
        # The execute_conversation_step will check current_step and stop at CONFIRM_SCRIPT
        graph.add_conditional_edges(
            "generate_script",
            self._should_proceed_after_script,
            {
                "confirm": "generate_content",  # Will be intercepted by execute_conversation_step if CONFIRM_SCRIPT
                "proceed": "generate_content"
            }
        )
        
        # Media handling flow
        graph.add_edge("handle_media", "validate_media")
        graph.add_edge("validate_media", "confirm_media")
        
        # Conditional edge after media confirmation
        graph.add_conditional_edges(
            "confirm_media",
            self._should_proceed_after_media,
            {
                "proceed": "generate_content",
                "edit_image": "edit_image",  # For Image Post, offer editing
                "thumbnail": "ask_thumbnail",
                "retry": "ask_media",
                "error": "handle_error"
            }
        )
        
        # After image editing, proceed to content generation
        graph.add_edge("edit_image", "generate_content")
        
        # After thumbnail selection, proceed to content generation
        graph.add_edge("ask_thumbnail", "generate_content")
        
        
        # Content generation flow - go to preview and edit
        graph.add_edge("generate_content", "preview_and_edit")
        
        # Conditional edge after preview and edit
        graph.add_conditional_edges(
            "preview_and_edit",
            self._should_proceed_after_preview,
            {
                "proceed": "select_schedule",
                "edit": "preview_and_edit",  # Stay in preview mode after edit
                "error": "handle_error"
            }
        )
        
        # Final flow
        graph.add_edge("select_schedule", "save_content")
        graph.add_edge("save_content", "ask_another_content")
        graph.add_edge("ask_another_content", END)
        
        # Error handling
        graph.add_edge("handle_error", END)
        
        return graph.compile()
    
    async def greet_user(self, state: CustomContentState) -> CustomContentState:
        """Welcome the user and initialize conversation"""
        try:
            # Create conversation ID
            conversation_id = str(uuid.uuid4())
            
            # Initialize conversation
            state["conversation_id"] = conversation_id
            state["conversation_messages"] = []
            state["current_step"] = ConversationStep.ASK_PLATFORM
            state["retry_count"] = 0
            state["is_complete"] = False
            state["retry_platform"] = False
            state["retry_content_type"] = False
            
            # Load user profile and platforms
            user_profile = await self._load_user_profile(state["user_id"])
            state["user_profile"] = user_profile
            
            connected_platforms = user_profile.get("social_media_platforms", [])
            state["platform_content_types"] = {platform: PLATFORM_CONTENT_TYPES.get(platform, []) for platform in connected_platforms}
            
            # Get business name from profile
            business_name = user_profile.get("business_name", "")
            if not business_name:
                business_name = "there"  # Fallback if no business name
            
            if not connected_platforms:
                # No platforms connected
                welcome_message = {
                    "role": "assistant",
                    "content": f"Thanks Emily, I'll take care from here. Hi {business_name}, Leo here! I'd love to help you create amazing content, but I don't see any connected social media platforms in your profile. Please connect your platforms first in the Settings dashboard, then come back to create content!",
                    "timestamp": datetime.now().isoformat()
                }
                state["conversation_messages"].append(welcome_message)
                state["current_step"] = ConversationStep.ERROR
                return state
            
            # Create platform selection message with options - more humanized
            # Format platform names for display (capitalize first letter)
            platform_options = []
            for platform in connected_platforms:
                # Capitalize first letter of each word for display
                display_name = ' '.join(word.capitalize() for word in platform.split('_'))
                platform_options.append({"value": platform, "label": display_name})
            
            welcome_message = {
                "role": "assistant",
                "content": f"Welcome, {business_name} team!\n\nLeo here — ready to craft powerful, custom content for your social media.\n\nChoose the platform you want to create content for, and let's get started!",
                "timestamp": datetime.now().isoformat(),
                "platforms": connected_platforms,
                "options": platform_options
            }
            
            state["conversation_messages"].append(welcome_message)
            state["progress_percentage"] = 15
            
            logger.info(f"Greeted user {state['user_id']} for custom content creation with {len(connected_platforms)} platforms")
            
        except Exception as e:
            logger.error(f"Error in greet_user: {e}")
            state["error_message"] = f"Failed to initialize conversation: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
        
    async def ask_platform(self, state: CustomContentState) -> CustomContentState:
        """Ask user to select a platform"""
        try:
            state["current_step"] = ConversationStep.ASK_PLATFORM
            state["progress_percentage"] = 15
            
            # Get user's connected platforms
            user_profile = state.get("user_profile", {})
            connected_platforms = user_profile.get("social_media_platforms", [])
            
            if not connected_platforms:
                message = {
                    "role": "assistant",
                    "content": "I don't see any connected social media platforms in your profile. Please connect your platforms first in the Settings dashboard.",
                    "timestamp": datetime.now().isoformat()
                }
                state["conversation_messages"].append(message)
                state["current_step"] = ConversationStep.ERROR
                return state
            
            # Check if we already asked (to avoid duplicate messages on retry)
            last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
            already_asked = last_message and (
                "platform" in last_message.get("content", "").lower() or 
                "select" in last_message.get("content", "").lower()
            )
            
            # Only add message if we haven't already asked (unless it's an error retry)
            if not already_asked or state.get("retry_platform", False):
                # Format platform names for display (capitalize first letter) - same as greet_user
                platform_options = []
                for platform in connected_platforms:
                    # Capitalize first letter of each word for display
                    display_name = ' '.join(word.capitalize() for word in platform.split('_'))
                    platform_options.append({"value": platform, "label": display_name})
                
                # Create platform selection message with options
                message = {
                    "role": "assistant",
                    "content": f"Great! I can see you have these platforms connected. Which platform would you like to create content for?",
                    "timestamp": datetime.now().isoformat(),
                    "platforms": connected_platforms,
                    "options": platform_options
                }
                state["conversation_messages"].append(message)
                state["retry_platform"] = False  # Reset retry flag
            
            logger.info(f"Asked user to select platform from: {connected_platforms}")
            
        except Exception as e:
            logger.error(f"Error in ask_platform: {e}")
            state["error_message"] = f"Failed to load platforms: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_content_type(self, state: CustomContentState) -> CustomContentState:
        """Ask user to select content type for the platform"""
        try:
            state["current_step"] = ConversationStep.ASK_CONTENT_TYPE
            state["progress_percentage"] = 25
            
            platform = state.get("selected_platform")
            if not platform:
                state["error_message"] = "No platform selected"
                state["current_step"] = ConversationStep.ERROR
                return state
            
            # Get content types for the platform
            content_types = PLATFORM_CONTENT_TYPES.get(platform, ["Text Post", "Image", "Video"])
            
            # Check if we already asked (to avoid duplicate messages on retry)
            last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
            already_asked = last_message and (
                "content type" in last_message.get("content", "").lower() or 
                "type of content" in last_message.get("content", "").lower()
            )
            
            # Only add message if we haven't already asked (unless it's an error retry)
            if not already_asked or state.get("retry_content_type", False):
                # Format platform name for display
                platform_display = ' '.join(word.capitalize() for word in platform.split('_'))
                
                message = {
                    "role": "assistant",
                    "content": f"Perfect! For {platform_display}, what type of content would you like to create?",
                    "timestamp": datetime.now().isoformat(),
                    "content_types": content_types,
                    "options": [{"value": content_type, "label": content_type} for content_type in content_types]
                }
                state["conversation_messages"].append(message)
                state["retry_content_type"] = False  # Reset retry flag
            
            logger.info(f"Asked user to select content type for {platform}")
            
        except Exception as e:
            logger.error(f"Error in ask_content_type: {e}")
            state["error_message"] = f"Failed to load content types: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_description(self, state: CustomContentState) -> CustomContentState:
        """Ask user to describe their content idea"""
        try:
            state["current_step"] = ConversationStep.ASK_DESCRIPTION
            state["progress_percentage"] = 35
            
            platform = state.get("selected_platform")
            content_type = state.get("selected_content_type")
            
            message = {
                "role": "assistant",
                "content": f"Great choice! Tell me what's in your mind for this {content_type}. Describe your idea, key points, reference styles, or anything specific you'd like included.",
                "timestamp": datetime.now().isoformat()
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Asked user to describe content for {content_type} on {platform}")
            
        except Exception as e:
            logger.error(f"Error in ask_description: {e}")
            state["error_message"] = f"Failed to ask for description: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_media(self, state: CustomContentState) -> CustomContentState:
        """Ask user about media preferences - handles Video/Photo/Text logic separately"""
        try:
            state["current_step"] = ConversationStep.ASK_MEDIA
            state["progress_percentage"] = 55
            
            platform = state.get("selected_platform")
            content_type = state.get("selected_content_type", "")
            content_type_lower = content_type.lower() if content_type else ""
            
            # 🔵 A. VIDEO CONTENT LOGIC
            if content_type_lower in ["reel", "shorts", "video"]:
                message = {
                    "role": "assistant",
                    "content": f"For your {content_type}, how would you like to proceed?",
                    "timestamp": datetime.now().isoformat(),
                    "options": [
                        {
                            "value": "upload_video",
                            "label": "🎥 Upload a video"
                        },
                        {
                            "value": "generate_script",
                            "label": "📝 Let Leo generate a script for you"
                        },
                        {
                            "value": "skip_media",
                            "label": "➖ Skip video (continue with text-only caption)"
                        }
                    ]
                }
                state["conversation_messages"].append(message)
                logger.info(f"Asked user about {content_type} media options for {platform}")
                return state
            
            # 🟣 B. PHOTO / CAROUSEL LOGIC
            if content_type_lower in ["image post", "photo", "carousel"]:
                # Check if this is a carousel post
                if content_type_lower == "carousel":
                    # Set platform-specific max images
                    if platform and platform.lower() == "facebook":
                        state["carousel_max_images"] = 10
                    elif platform and platform.lower() == "instagram":
                        state["carousel_max_images"] = 20
                    else:
                        state["carousel_max_images"] = 10  # Default
                    
                    # Initialize carousel fields
                    state["carousel_images"] = []
                    state["uploaded_carousel_images"] = []
                    state["current_carousel_index"] = 0
                    state["carousel_upload_done"] = False
                    
                    # Ask for carousel image source
                    state["current_step"] = ConversationStep.ASK_CAROUSEL_IMAGE_SOURCE
                    max_images = state["carousel_max_images"]
                    
                    message = {
                        "role": "assistant",
                        "content": f"How would you like to add visuals for this post?",
                        "timestamp": datetime.now().isoformat(),
                        "options": [
                            {
                                "value": "upload_image",
                                "label": "📸 Upload photo(s)"
                            },
                            {
                                "value": "ai_generate",
                                "label": "🎨 Let Leo generate images for you"
                            },
                            {
                                "value": "skip_media",
                                "label": "➖ Create without images"
                            }
                        ]
                    }
                    state["conversation_messages"].append(message)
                    logger.info(f"Asked user about carousel image source for {platform}")
                    return state
                else:
                    # Single image post
                    message = {
                        "role": "assistant",
                        "content": f"How would you like to add visuals for this post?",
                        "timestamp": datetime.now().isoformat(),
                        "options": [
                            {
                                "value": "upload_image",
                                "label": "📸 Upload photo(s)"
                            },
                            {
                                "value": "generate_image",
                                "label": "🎨 Let Leo generate images for you"
                            },
                            {
                                "value": "skip_media",
                                "label": "➖ Create without images"
                            }
                        ]
                    }
                    state["conversation_messages"].append(message)
                    logger.info(f"Asked user about {content_type} media options for {platform}")
                    return state
            
            # 🟢 C. TEXT POST LOGIC - Skip media step
            if content_type_lower == "text post":
                # Skip media for text posts - go directly to content generation
                logger.info(f"Skipping media step for {content_type} on {platform}")
                state["has_media"] = False
                state["should_generate_media"] = False
                state["current_step"] = ConversationStep.GENERATE_CONTENT
                return state
            
            # Default fallback for other content types
            # Get media requirements for the platform
            media_reqs = PLATFORM_MEDIA_REQUIREMENTS.get(platform, {})
            
            message = {
                "role": "assistant",
                "content": f"Do you have media to include with your {content_type}? What would you prefer?",
                "timestamp": datetime.now().isoformat(),
                "media_requirements": media_reqs,
                "options": [
                    {
                        "value": "upload_image",
                        "label": "📷 Upload an image"
                    },
                    {
                        "value": "upload_video", 
                        "label": "🎥 Upload a video"
                    },
                    {
                        "value": "generate_image",
                        "label": "🎨 Let me generate an image for you"
                    },
                    {
                        "value": "generate_video",
                        "label": "🎬 Let me generate a video for you"
                    },
                    {
                        "value": "skip_media",
                        "label": "📝 Skip media (text-only post)"
                    }
                ]
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Asked user about media preferences for {platform}")
            
        except Exception as e:
            logger.error(f"Error in ask_media: {e}")
            state["error_message"] = f"Failed to ask about media: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def handle_media(self, state: CustomContentState) -> CustomContentState:
        """Handle media upload - show upload interface"""
        try:
            state["current_step"] = ConversationStep.HANDLE_MEDIA
            state["progress_percentage"] = 55
            
            media_type = state.get("media_type", "image")
            media_type_name = "image" if media_type == "image" else "video"
            
            message = {
                "role": "assistant",
                "content": f"Perfect! Please upload your {media_type_name} below.",
                "timestamp": datetime.now().isoformat()
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Ready for media upload: {media_type}")
            
        except Exception as e:
            logger.error(f"Error in handle_media: {e}")
            state["error_message"] = f"Failed to handle media: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def validate_media(self, state: CustomContentState) -> CustomContentState:
        """Validate uploaded media against platform requirements"""
        try:
            state["current_step"] = ConversationStep.VALIDATE_MEDIA
            state["progress_percentage"] = 65
            
            # Media validation will be handled by the frontend
            # This is a placeholder for any server-side validation
            message = {
                "role": "assistant",
                "content": "Media validation completed successfully!",
                "timestamp": datetime.now().isoformat()
            }
            state["conversation_messages"].append(message)
            
            logger.info("Media validation completed")
            
        except Exception as e:
            logger.error(f"Error in validate_media: {e}")
            state["error_message"] = f"Failed to validate media: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state

    async def confirm_media(self, state: CustomContentState) -> CustomContentState:
        """Ask user to confirm if the uploaded media is correct, then route to thumbnail selection for videos"""
        try:
            state["current_step"] = ConversationStep.CONFIRM_MEDIA
            state["progress_percentage"] = 60
            
            # Check if media is already confirmed - if so, let the graph route handle it
            if state.get("media_confirmed", False):
                logger.info("Media already confirmed, letting graph route handle next step")
                return state
            
            media_url = state.get("uploaded_media_url")
            media_type = state.get("uploaded_media_type", "")
            media_filename = state.get("uploaded_media_filename", "")
            uploaded_media_type = state.get("media_type", "")
            
            # Check if this is a video - route to thumbnail selection after confirmation
            if uploaded_media_type == MediaType.VIDEO or "video" in media_type.lower():
                # For videos, after confirmation, ask about thumbnail
                state["media_confirmed"] = True
                state["current_step"] = ConversationStep.ASK_THUMBNAIL
                return await self.ask_thumbnail(state)
            
            # Check if we've already asked for confirmation (avoid duplicate messages)
            last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
            confirmation_message = "Is this the correct media you'd like me to use for your content?"
            
            if last_message and confirmation_message in last_message.get("content", ""):
                # Already asked, don't ask again
                logger.info("Already asked for media confirmation, skipping duplicate")
                return state
            
            # For images, use standard confirmation flow
            message = {
                "role": "assistant",
                "content": f"Perfect! I've received your {media_type.split('/')[0]} file.\n\nIs this the correct media you'd like me to use for your content? Please confirm by typing 'yes' to proceed or 'no' to upload a different file.",
                "timestamp": datetime.now().isoformat(),
                "media_url": media_url,
                "media_type": media_type,
                "media_filename": media_filename
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Asking user to confirm media: {media_filename}")
            
        except Exception as e:
            logger.error(f"Error in confirm_media: {e}")
            state["error_message"] = f"Failed to confirm media: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_thumbnail(self, state: CustomContentState) -> CustomContentState:
        """Ask user to select thumbnail style for video"""
        try:
            state["current_step"] = ConversationStep.ASK_THUMBNAIL
            state["progress_percentage"] = 62
            
            video_url = state.get("uploaded_media_url")
            content_type = state.get("selected_content_type", "")
            
            message = {
                "role": "assistant",
                "content": f"Great! Now choose your thumbnail style:",
                "timestamp": datetime.now().isoformat(),
                "video_url": video_url,
                "options": [
                    {
                        "value": "upload_thumbnail",
                        "label": "📷 Upload a thumbnail"
                    },
                    {
                        "value": "generate_thumbnail",
                        "label": "🎨 Let Leo generate a thumbnail"
                    },
                    {
                        "value": "auto_extract",
                        "label": "🎬 Auto-extract a frame from your video"
                    }
                ]
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Asked user to select thumbnail style for {content_type}")
            
        except Exception as e:
            logger.error(f"Error in ask_thumbnail: {e}")
            state["error_message"] = f"Failed to ask about thumbnail: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_carousel_image_source(self, state: CustomContentState, user_input: str = None) -> CustomContentState:
        """Handle carousel image source selection (AI generate or manual upload)"""
        try:
            if not user_input:
                # This should not happen as we already asked in ask_media
                return state
            
            user_input_lower = user_input.lower().strip()
            
            if user_input_lower == "ai_generate" or "generate" in user_input_lower:
                state["carousel_image_source"] = "ai_generate"
                state["current_carousel_index"] = 0
                state["carousel_images"] = []
                # Initialize carousel theme based on user description for sequential consistency
                user_description = state.get("user_description", "")
                state["carousel_theme"] = f"Sequential carousel story about: {user_description}"
                state["current_step"] = ConversationStep.GENERATE_CAROUSEL_IMAGE
                return await self.generate_carousel_image(state)
            elif user_input_lower == "manual_upload" or "upload" in user_input_lower:
                state["carousel_image_source"] = "manual_upload"
                state["uploaded_carousel_images"] = []
                state["carousel_upload_done"] = False
                state["current_step"] = ConversationStep.HANDLE_CAROUSEL_UPLOAD
                return await self.handle_carousel_upload(state)
            else:
                # Invalid input, ask again
                max_images = state.get("carousel_max_images", 10)
                message = {
                    "role": "assistant",
                    "content": f"Please choose either 'Generate with AI' or 'Upload manually'. How would you like to add images to your carousel?",
                    "timestamp": datetime.now().isoformat(),
                    "options": [
                        {
                            "value": "ai_generate",
                            "label": "🎨 Generate with AI (4 images max)"
                        },
                        {
                            "value": "manual_upload",
                            "label": f"📤 Upload manually (up to {max_images} images)"
                        }
                    ]
                }
                state["conversation_messages"].append(message)
                return state
                
        except Exception as e:
            logger.error(f"Error in ask_carousel_image_source: {e}")
            state["error_message"] = f"Failed to process carousel image source: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
    
    async def generate_carousel_image(self, state: CustomContentState, user_input: str = None) -> CustomContentState:
        """Generate all 4 carousel images at once"""
        try:
            # This step just indicates that generation should start
            # The actual generation will be handled by the API endpoint which generates all 4 at once
            state["current_step"] = ConversationStep.GENERATE_CAROUSEL_IMAGE
            state["progress_percentage"] = 50
            state["carousel_images"] = []
            state["current_carousel_index"] = 0
            
            message = {
                "role": "assistant",
                "content": "Generating all 4 carousel images for you... This may take a moment. I'll create a cohesive sequential story across all images.",
                "timestamp": datetime.now().isoformat(),
                "generating_all": True,
                "total_images": 4
            }
            state["conversation_messages"].append(message)
            
            return state
            
        except Exception as e:
            logger.error(f"Error in generate_carousel_image: {e}")
            state["error_message"] = f"Failed to generate carousel image: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
    
    async def approve_carousel_images(self, state: CustomContentState, user_input: str = None) -> CustomContentState:
        """Handle user approval of all carousel images"""
        try:
            carousel_images = state.get("carousel_images", [])
            
            if not user_input:
                # Show all images with original and edited versions, plus editing options
                if carousel_images and len(carousel_images) >= 1:
                    image_count = len(carousel_images)
                    message = {
                        "role": "assistant",
                        "content": f"Perfect! I've generated {image_count} carousel image(s) for you. Review them below - you'll see both the original and an improved version for each image.\n\nYou can edit any image with these options:",
                        "timestamp": datetime.now().isoformat(),
                        "carousel_images": [img.get("url") for img in carousel_images if img.get("url")],
                        "show_editing_options": True,
                        "editing_options": [
                            {"value": "background_change", "label": "🎨 Background change"},
                            {"value": "color_correction", "label": "🌈 Color correction"},
                            {"value": "filters", "label": "✨ Filters"},
                            {"value": "sharpness", "label": "🔍 Sharpness"},
                            {"value": "crop", "label": "✂️ Crop"},
                            {"value": "cleanup", "label": "🧹 Clean-up"}
                        ],
                        "options": [
                            {"value": "approve", "label": "✅ Approve and continue"},
                            {"value": "regenerate", "label": "🔄 Regenerate all images"},
                            {"value": "manual_upload", "label": "📤 Switch to manual upload"}
                        ]
                    }
                    state["conversation_messages"].append(message)
                    state["current_step"] = ConversationStep.APPROVE_CAROUSEL_IMAGES
                    return state
                else:
                    # Not all images generated yet, wait
                    message = {
                        "role": "assistant",
                        "content": "Still generating carousel images... Please wait.",
                        "timestamp": datetime.now().isoformat()
                    }
                    state["conversation_messages"].append(message)
                    return state
            
            user_input_lower = user_input.lower().strip() if user_input else ""
            # Remove emojis and normalize the input
            import re
            user_input_clean = re.sub(r'[^\w\s]', '', user_input_lower)  # Remove all non-alphanumeric except spaces
            user_input_clean = user_input_clean.strip()
            
            # Check for approval - handle various formats
            if (user_input_lower == "approve" or 
                user_input_lower == "yes" or 
                "approve" in user_input_clean or 
                ("yes" in user_input_clean and "approve" in user_input_clean) or
                user_input_clean == "yes approve and continue"):
                # User approved, proceed directly to content generation
                state["current_step"] = ConversationStep.GENERATE_CONTENT
                # Don't add intermediate message, go directly to content generation
                return await self.generate_content(state)
            elif ("regenerate" in user_input_clean or 
                  user_input_lower == "regenerate" or 
                  user_input_lower == "regenerate_all" or
                  "regenerate all" in user_input_clean):
                # User wants to regenerate all images
                state["carousel_images"] = []
                state["current_carousel_index"] = 0
                state["current_step"] = ConversationStep.GENERATE_CAROUSEL_IMAGE
                # Call generate_carousel_image which will set generating_all flag
                return await self.generate_carousel_image(state)
            elif ("manual" in user_input_clean and "upload" in user_input_clean) or \
                 user_input_lower == "manual_upload" or \
                 user_input_lower == "upload" or \
                 "switch to manual" in user_input_clean:
                # User wants to switch to manual upload
                state["carousel_image_source"] = "manual_upload"
                state["carousel_images"] = []  # Clear generated images
                state["uploaded_carousel_images"] = []
                state["carousel_upload_done"] = False
                state["current_step"] = ConversationStep.HANDLE_CAROUSEL_UPLOAD
                return await self.handle_carousel_upload(state)
            
            return state
            
        except Exception as e:
            logger.error(f"Error in approve_carousel_images: {e}")
            state["error_message"] = f"Failed to approve carousel images: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
    
    async def handle_carousel_upload(self, state: CustomContentState) -> CustomContentState:
        """Handle bulk carousel image uploads"""
        try:
            state["current_step"] = ConversationStep.HANDLE_CAROUSEL_UPLOAD
            state["progress_percentage"] = 55
            
            max_images = state.get("carousel_max_images", 10)
            uploaded_carousel_images = state.get("uploaded_carousel_images") or []
            uploaded_count = len(uploaded_carousel_images)
            remaining = max_images - uploaded_count
            
            message = {
                "role": "assistant",
                "content": "Please upload your carousel images below.",
                "timestamp": datetime.now().isoformat(),
                "max_images": max_images,
                "uploaded_count": uploaded_count,
                "remaining": remaining,
                # Include uploaded images in message so frontend can display them
                "uploaded_carousel_images": uploaded_carousel_images if uploaded_carousel_images else []
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Ready for carousel upload: {uploaded_count}/{max_images}")
            
        except Exception as e:
            logger.error(f"Error in handle_carousel_upload: {e}")
            state["error_message"] = f"Failed to handle carousel upload: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def confirm_carousel_upload_done(self, state: CustomContentState, user_input: str = None) -> CustomContentState:
        """Ask if carousel upload is complete"""
        try:
            uploaded_carousel_images = state.get("uploaded_carousel_images") or []
            uploaded_count = len(uploaded_carousel_images)
            max_images = state.get("carousel_max_images", 10)
            
            if not user_input:
                # Ask if done
                state["current_step"] = ConversationStep.CONFIRM_CAROUSEL_UPLOAD_DONE
                message = {
                    "role": "assistant",
                    "content": f"You've uploaded {uploaded_count} image(s). Are you done uploading images?",
                    "timestamp": datetime.now().isoformat(),
                    "options": [
                        {"value": "yes", "label": "✅ Yes, I'm done"},
                        {"value": "no", "label": "📤 No, add more images"}
                    ],
                    # Include uploaded images in message so frontend can display them
                    "uploaded_carousel_images": uploaded_carousel_images if uploaded_carousel_images else []
                }
                state["conversation_messages"].append(message)
                return state
            
            user_input_lower = user_input.lower().strip()
            
            if user_input_lower == "yes" or user_input_lower == "done":
                # User is done, proceed directly to content generation
                state["carousel_upload_done"] = True
                state["current_step"] = ConversationStep.GENERATE_CONTENT
                # Don't add intermediate message, go directly to content generation
                return await self.generate_content(state)
            elif user_input_lower == "no":
                # User wants to add more, show upload interface again
                if uploaded_count >= max_images:
                    # Reached max, proceed directly to content generation
                    state["carousel_upload_done"] = True
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    return await self.generate_content(state)
                else:
                    state["current_step"] = ConversationStep.HANDLE_CAROUSEL_UPLOAD
                    return await self.handle_carousel_upload(state)
            
            return state
            
        except Exception as e:
            logger.error(f"Error in confirm_carousel_upload_done: {e}")
            state["error_message"] = f"Failed to confirm carousel upload: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state

    async def generate_script(self, state: CustomContentState, changes: str = None) -> CustomContentState:
        """Generate a video script for Reel using content creation agent logic
        
        Args:
            state: Current conversation state
            changes: Optional string with user's requested changes/modifications for regeneration
        """
        try:
            logger.info("🎬 Starting script generation...")
            state["current_step"] = ConversationStep.GENERATE_SCRIPT
            state["progress_percentage"] = 60
            
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            user_description = state.get("user_description", "")
            clarification_1 = state.get("clarification_1", "")
            clarification_2 = state.get("clarification_2", "")
            clarification_3 = state.get("clarification_3", "")
            
            # Check if this is a regeneration with changes
            is_regeneration = changes is not None
            previous_script = state.get("generated_script")
            script_history = state.get("script_history", [])
            
            logger.info(f"Script generation context - Platform: {platform}, Content Type: {content_type}, Description: {user_description[:50]}..., Regeneration: {is_regeneration}")
            
            # Load business context
            business_context = self._load_business_context(state["user_id"])
            logger.info(f"Business context loaded: {business_context.get('business_name', 'N/A')}")
            
            # Create script generation prompt
            script_prompt = f"""Create a professional video script for an Instagram Reel based on the following information:

User's Content Idea: "{user_description}"

Business Context:
- Business Name: {business_context.get('business_name', 'Not specified')}
- Industry: {business_context.get('industry', 'Not specified')}
- Target Audience: {business_context.get('target_audience', 'General audience')}
- Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
- Brand Personality: {business_context.get('brand_personality', 'Approachable and trustworthy')}
"""
            
            if clarification_1:
                script_prompt += f"\nPost Goal/Purpose: {clarification_1}"
            if clarification_2:
                script_prompt += f"\nTarget Audience Details: {clarification_2}"
            if clarification_3:
                script_prompt += f"\nTone/Style: {clarification_3}"
            
            # If this is a regeneration with changes, include previous script and requested changes
            if is_regeneration and previous_script:
                script_prompt += f"""

PREVIOUS SCRIPT (to be modified):
{json.dumps(previous_script, indent=2)}

USER REQUESTED CHANGES/INCLUSIONS:
{changes}

IMPORTANT INSTRUCTIONS:
1. Review the PREVIOUS SCRIPT above carefully
2. Apply the USER REQUESTED CHANGES/INCLUSIONS while keeping the good parts that weren't mentioned for change
3. Maintain the same JSON structure and format
4. Only modify what the user specifically requested - keep everything else intact
5. Ensure the modified script is coherent and flows naturally
6. If the user wants to add something, integrate it seamlessly
7. If the user wants to change tone/style, update the entire script accordingly
8. Return the complete modified script, not just the changed parts
"""
            
            script_prompt += """

Requirements for the Instagram Reel Script:
1. Keep it engaging and hook viewers in the first 3 seconds
2. Structure it for a 15-90 second video (typical Reel length)
3. Include clear visual cues and scene descriptions
4. Add on-screen text suggestions where appropriate
5. Include a strong call-to-action at the end
6. Match the brand voice and personality
7. Make it shareable and relatable
8. Include relevant hashtag suggestions

Format the script as JSON with this structure:
{
    "title": "Script title",
    "hook": "Opening hook (first 3-5 seconds)",
    "scenes": [
        {
            "duration": "X seconds",
            "visual": "What to show on screen",
            "audio": "What to say/narrate",
            "on_screen_text": "Text overlay (if any)"
        }
    ],
    "call_to_action": "Ending CTA",
    "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
    "total_duration": "Estimated total duration",
    "tips": "Additional production tips"
}

Return ONLY valid JSON, no markdown code blocks."""
            
            # Generate script using OpenAI
            logger.info("📝 Calling OpenAI API to generate script...")
            # Use asyncio.to_thread to run the synchronous OpenAI call in a thread pool
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.chat.completions.create,
                    model="gpt-4",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert video scriptwriter specializing in Instagram Reels and short-form video content. Create engaging, viral-worthy scripts that drive engagement."
                        },
                        {
                            "role": "user",
                            "content": script_prompt
                        }
                    ],
                    max_tokens=2000,
                    temperature=0.7
                ),
                timeout=30.0
            )
            logger.info("✅ OpenAI API response received")
            
            # Parse JSON response
            raw_response = response.choices[0].message.content.strip()
            
            # Try to extract JSON from markdown code blocks
            if "```json" in raw_response:
                json_start = raw_response.find("```json") + 7
                json_end = raw_response.find("```", json_start)
                if json_end != -1:
                    raw_response = raw_response[json_start:json_end].strip()
            elif "```" in raw_response:
                json_start = raw_response.find("```") + 3
                json_end = raw_response.find("```", json_start)
                if json_end != -1:
                    raw_response = raw_response[json_start:json_end].strip()
            
            # Try to find JSON object in the response
            if raw_response.startswith('{') and raw_response.endswith('}'):
                json_text = raw_response
            else:
                # Look for JSON object within the text
                start_idx = raw_response.find('{')
                end_idx = raw_response.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_text = raw_response[start_idx:end_idx + 1]
                else:
                    json_text = raw_response
            
            try:
                script_data = json.loads(json_text)
                
                # Validate and normalize script structure
                script_data = self._validate_script_structure(script_data, user_description)
                
                logger.info(f"✅ Script JSON parsed and validated successfully: {script_data.get('title', 'N/A')}")
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parsing failed for script: {e}")
                logger.warning(f"Raw response was: {raw_response[:200]}...")
                # Fallback script structure
                fallback_script = {
                    "title": f"Reel Script: {user_description[:50] if user_description else 'Untitled'}",
                    "hook": user_description[:100] if user_description else "",
                    "scenes": [
                        {
                            "duration": "15-30 seconds",
                            "visual": "Show the main content",
                            "audio": user_description if user_description else "",
                            "on_screen_text": "Key message"
                        }
                    ],
                    "call_to_action": "Follow for more!",
                    "hashtags": [],
                    "total_duration": "30 seconds",
                    "tips": "Keep it engaging and authentic"
                }
                # Validate fallback script structure
                script_data = self._validate_script_structure(fallback_script, user_description)
                logger.info("Using fallback script structure")
            
            # Store script in cache memory (script_history array)
            # Initialize script_history if it doesn't exist
            if "script_history" not in state:
                state["script_history"] = []
            
            # Add script to history with timestamp and version number
            script_version = {
                "script": script_data,
                "version": len(state["script_history"]) + 1,
                "timestamp": datetime.now().isoformat(),
                "is_current": True,
                "changes": changes if is_regeneration else None
            }
            
            # Mark all previous scripts as not current
            for prev_script in state["script_history"]:
                prev_script["is_current"] = False
            
            # Add new script to history (keep all previous scripts)
            state["script_history"].append(script_version)
            
            # Also store current script for easy access
            state["generated_script"] = script_data
            state["current_script_version"] = script_version["version"]
            
            logger.info(f"✅ Script v{script_version['version']} stored in cache memory with {len(script_data.get('scenes', []))} scenes")
            logger.info(f"📝 Total scripts in cache: {len(state['script_history'])}")
            
            # Create message with all scripts (both old and new)
            message_text = f"Perfect! I've generated a video script for your {content_type}." if not is_regeneration else f"Great! I've updated the script based on your changes. Here are all your script versions:"
            
            script_message = {
                "role": "assistant",
                "content": f"{message_text} Review them below and choose an option for each.",
                "timestamp": datetime.now().isoformat(),
                "script": script_data,  # Current/latest script
                "script_version": script_version["version"],
                "all_scripts": [s["script"] for s in state["script_history"]],  # All scripts for display
                "script_history": state["script_history"]  # Full history with metadata
            }
            
            # Remove old script messages to avoid duplicates (keep only the latest with all scripts)
            if is_regeneration:
                state["conversation_messages"] = [
                    msg for msg in state.get("conversation_messages", [])
                    if not msg.get("script")  # Remove messages with script
                ]
            
            state["conversation_messages"].append(script_message)
            state["progress_percentage"] = 70
            
            # Stay on CONFIRM_SCRIPT step to allow user to save or regenerate
            state["current_step"] = ConversationStep.CONFIRM_SCRIPT
            
            logger.info(f"Generated script for {content_type} on {platform}")
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout generating script - API call took too long")
            state["error_message"] = "Script generation timed out. Please try again."
            state["current_step"] = ConversationStep.ERROR
        except Exception as e:
            logger.error(f"Error generating script: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            state["error_message"] = f"Failed to generate script: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def generate_content(self, state: CustomContentState) -> CustomContentState:
        """Generate content using the content creation agent logic with image analysis"""
        try:
            state["current_step"] = ConversationStep.GENERATE_CONTENT
            state["progress_percentage"] = 75
            
            # Extract context
            user_description = state.get("user_description", "")
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            uploaded_media_url = state.get("uploaded_media_url", "")
            generated_media_url = state.get("generated_media_url", "")
            has_media = state.get("has_media", False)
            media_type = state.get("media_type", "")
            generated_script = state.get("generated_script")  # Get generated script if available
            
            # Check if this is an Image Post - handle specially
            is_image_post = content_type.lower() in ["image post", "image", "photo"]
            is_carousel = content_type.lower() == "carousel"
            
            # SPECIAL HANDLING FOR IMAGE POST: Generate short caption only
            # Use edited image URL if available, otherwise uploaded or generated
            image_url_for_post = state.get("edited_image_url") or uploaded_media_url or generated_media_url
            if is_image_post and has_media and image_url_for_post and not is_carousel:
                return await self._generate_image_post_content(state, image_url_for_post, user_description, platform, content_type)
            carousel_images = []
            
            if is_carousel:
                # Get carousel images - either AI-generated or manually uploaded
                carousel_image_source = state.get("carousel_image_source", "")
                if carousel_image_source == "ai_generate":
                    # Get AI-generated carousel images
                    carousel_images_data = state.get("carousel_images", [])
                    if carousel_images_data:
                        carousel_images = [img.get("url") for img in carousel_images_data if img.get("url")]
                elif carousel_image_source == "manual_upload":
                    # Get manually uploaded carousel images
                    carousel_images = state.get("uploaded_carousel_images") or []
                    if not isinstance(carousel_images, list):
                        carousel_images = []
            
            # Determine which media URL to use (uploaded or generated) - for non-carousel posts
            media_url = uploaded_media_url or generated_media_url
            
            # Load business context if not already loaded
            business_context = state.get("business_context")
            if not business_context:
                user_id = state.get("user_id")
                if user_id:
                    business_context = self._load_business_context(user_id)
                    state["business_context"] = business_context
                else:
                    business_context = {}
            
            # Analyze image(s) if available
            image_analysis = ""
            if is_carousel and carousel_images:
                # Analyze all carousel images
                try:
                    image_analyses = []
                    for idx, img_url in enumerate(carousel_images):
                        try:
                            analysis = await self._analyze_uploaded_image(img_url, user_description, business_context)
                            if analysis and not analysis.startswith("Image analysis failed"):
                                image_analyses.append(f"Image {idx + 1}: {analysis}")
                                logger.info(f"Carousel image {idx + 1} analysis completed successfully")
                            else:
                                # Analysis failed but handled gracefully - don't log as error
                                logger.warning(f"Carousel image {idx + 1} analysis skipped (timeout or download issue)")
                                image_analyses.append(f"Image {idx + 1}: Analysis skipped due to timeout")
                        except Exception as e:
                            # Only log as error if it's not a timeout/download issue
                            if "timeout" not in str(e).lower() and "downloading" not in str(e).lower():
                                logger.error(f"Carousel image {idx + 1} analysis failed: {e}")
                            else:
                                logger.warning(f"Carousel image {idx + 1} analysis timeout (handled gracefully)")
                            image_analyses.append(f"Image {idx + 1}: Analysis skipped")
                    image_analysis = "\n\n".join(image_analyses)
                    logger.info("All carousel images analyzed successfully")
                except Exception as e:
                    logger.error(f"Carousel image analysis failed: {e}")
                    image_analysis = f"Carousel image analysis failed: {str(e)}"
            elif has_media and media_url and media_type == "image":
                # Analyze single image (non-carousel)
                try:
                    image_analysis = await self._analyze_uploaded_image(media_url, user_description, business_context)
                    logger.info("Image analysis completed successfully")
                except Exception as e:
                    logger.error(f"Image analysis failed: {e}")
                    image_analysis = f"Image analysis failed: {str(e)}"
            
            # Create enhanced content generation prompt
            # For carousel, indicate we have multiple images
            has_images_for_analysis = (is_carousel and carousel_images) or (has_media and media_url and media_type == "image")
            clarification_1 = state.get("clarification_1", "")
            clarification_2 = state.get("clarification_2", "")
            clarification_3 = state.get("clarification_3", "")
            prompt = self._create_enhanced_content_prompt(
                user_description, platform, content_type, business_context, image_analysis, has_images_for_analysis,
                clarification_1, clarification_2, clarification_3, generated_script
            )
            
            # Prepare messages for content generation
            messages = [
                {"role": "system", "content": "You are an expert social media content creator. Generate engaging, platform-optimized content that incorporates visual elements when provided. CRITICAL: Return ONLY a valid JSON object with the exact fields specified. Do NOT include any markdown formatting, code blocks, or nested JSON. The response must be pure JSON that can be parsed directly."},
                {"role": "user", "content": prompt}
            ]
            
            # Add image(s) to messages if available
            if is_carousel and carousel_images:
                # Add all carousel images
                image_content = [{"type": "text", "text": f"Here are the {len(carousel_images)} carousel images to incorporate into the content. Analyze them as a sequence and create content that works across all images:"}]
                for img_url in carousel_images:
                    image_content.append({"type": "image_url", "image_url": {"url": img_url}})
                messages.append({
                    "role": "user",
                    "content": image_content
                })
            elif has_media and media_url and media_type == "image":
                # Add single image (non-carousel)
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Here's the image to incorporate into the content:"},
                        {"type": "image_url", "image_url": {"url": media_url}}
                    ]
                })
            
            # Generate content using OpenAI with vision capabilities
            # Handle timeout errors gracefully - continue without images if timeout occurs
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",  # Use vision-capable model
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000,
                    timeout=60  # 60 second timeout
                )
                generated_text = response.choices[0].message.content
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error generating content with images: {e}")
                
                # If timeout or image download error, try without images
                if "timeout" in error_msg.lower() or "invalid_image_url" in error_msg.lower() or "downloading" in error_msg.lower():
                    logger.warning("Image download timeout, generating content without images")
                    # Remove image messages and retry with text only
                    text_only_messages = [
                        {"role": "system", "content": messages[0]["content"]},
                        {"role": "user", "content": prompt + "\n\nNote: Carousel images are available but couldn't be analyzed due to timeout. Generate content based on the description and theme."}
                    ]
                    try:
                        response = self.client.chat.completions.create(
                            model="gpt-4o",
                            messages=text_only_messages,
                            temperature=0.7,
                            max_tokens=1000
                        )
                        generated_text = response.choices[0].message.content
                    except Exception as e2:
                        logger.error(f"Error generating content without images: {e2}")
                        raise e2
                else:
                    # Other errors, re-raise
                    raise e
            
            # Parse the generated content
            try:
                # Try to parse as JSON first
                content_data = json.loads(generated_text)
            except json.JSONDecodeError:
                # If not JSON, create a structured response
                content_data = {
                    "content": generated_text,
                    "title": f"{content_type} for {platform}",
                    "hashtags": self._extract_hashtags(generated_text),
                    "post_type": "carousel" if is_carousel else ("image" if has_media else "text"),
                    "media_url": uploaded_media_url if (has_media and not is_carousel) else None
                }
            
            # Ensure uploaded image is always included for Image Post
            if content_type.lower() in ["image post", "photo"] and has_media and uploaded_media_url and not is_carousel:
                content_data["media_url"] = uploaded_media_url
                content_data["post_type"] = "image"
                logger.info(f"Including uploaded image in Image Post: {uploaded_media_url}")
            
            # Add carousel images to content data if this is a carousel post
            if is_carousel and carousel_images:
                content_data["carousel_images"] = carousel_images
                content_data["post_type"] = "carousel"
            
            state["generated_content"] = content_data
            
            # Create response message with the generated content displayed directly
            if is_carousel and carousel_images:
                # Carousel post with images
                if image_analysis and not image_analysis.startswith("Carousel image analysis failed"):
                    message_content = f"Perfect! I've analyzed your {len(carousel_images)} carousel images and generated your {content_type} content. Here's what I created:\n\n**{content_data.get('title', f'{content_type} for {platform}')}**\n\n{content_data.get('content', '')}"
                else:
                    message_content = f"Great! I've generated your {content_type} content based on your {len(carousel_images)} carousel images. Here's what I created:\n\n**{content_data.get('title', f'{content_type} for {platform}')}**\n\n{content_data.get('content', '')}"
            elif has_media and image_analysis and not image_analysis.startswith("Image analysis failed"):
                message_content = f"Perfect! I've analyzed your image and generated your {content_type} content. Here's what I created:\n\n**{content_data.get('title', f'{content_type} for {platform}')}**\n\n{content_data.get('content', '')}"
            else:
                message_content = f"Great! I've generated your {content_type} content. Here's what I created:\n\n**{content_data.get('title', f'{content_type} for {platform}')}**\n\n{content_data.get('content', '')}"
                
            # Add hashtags if available (for all cases)
                if content_data.get('hashtags'):
                    hashtags = ' '.join([f"#{tag.replace('#', '')}" for tag in content_data['hashtags']])
                    message_content += f"\n\n{hashtags}"
                
            # Add call to action if available (for all cases)
                if content_data.get('call_to_action'):
                    message_content += f"\n\n**Call to Action:** {content_data['call_to_action']}"
            
            # Prepare message with carousel images if applicable
            message = {
                "role": "assistant",
                "content": message_content,
                "timestamp": datetime.now().isoformat(),
                "has_media": has_images_for_analysis,
                "media_url": uploaded_media_url if (has_media and not is_carousel) else None,
                "media_type": media_type if (has_media and not is_carousel) else None,
                # Include carousel images in the message
                "carousel_images": carousel_images if is_carousel else None,
                # Explicitly set structured_content to null to prevent frontend from creating cards
                "structured_content": None
            }
            state["conversation_messages"].append(message)
            
            logger.info(f"Generated content for {platform} {content_type}")
            
            # If media generation is needed, generate it now using the created content
            if state.get("should_generate_media", False) and self.media_agent:
                logger.info("Generating media based on created content")
                try:
                    # Get the generated content from state
                    generated_content = state.get("generated_content", {})
                    
                    # Create a minimal temporary post for media generation (will be cleaned up)
                    temp_post_id = await self._create_temp_post_for_media(state)
                    
                    if temp_post_id:
                        # Update the temporary post with the generated content
                        await self._update_temp_post_with_content(temp_post_id, generated_content, state)
                        
                        # Generate media using the content
                        media_result = await self.media_agent.generate_media_for_post(temp_post_id)
                        
                        if media_result["success"] and media_result.get("image_url"):
                            # Update state with generated media
                            state["generated_media_url"] = media_result["image_url"]
                            state["media_type"] = MediaType.IMAGE
                            state["has_media"] = True
                            
                            # Update generated_content with the media URL (important for Image Posts)
                            if state.get("generated_content"):
                                state["generated_content"]["media_url"] = media_result["image_url"]
                                # Ensure type is set correctly for Image Posts
                                content_type = state.get("selected_content_type", "").lower()
                                if content_type in ["image post", "image", "photo"]:
                                    state["generated_content"]["type"] = "image_post"
                                    state["generated_content"]["post_type"] = "image"
                            
                            # Update content history if it exists (to include the generated media URL)
                            if state.get("content_history") and len(state["content_history"]) > 0:
                                # Update the most recent version in history
                                latest_version = state["content_history"][-1]
                                if latest_version.get("content"):
                                    latest_version["content"]["media_url"] = media_result["image_url"]
                                    content_type = state.get("selected_content_type", "").lower()
                                    if content_type in ["image post", "image", "photo"]:
                                        latest_version["content"]["type"] = "image_post"
                                        latest_version["content"]["post_type"] = "image"
                            
                            # Update the content message to include the generated image
                            state["conversation_messages"][-1]["media_url"] = media_result["image_url"]
                            state["conversation_messages"][-1]["media_type"] = "image"
                            
                            logger.info(f"Media generation completed successfully: {media_result['image_url']}")
                        else:
                            logger.warning(f"Media generation failed: {media_result.get('error', 'Unknown error')}")
                            # Continue without media
                            state["should_generate_media"] = False
                            state["has_media"] = False
                        
                        # Clean up the temporary post to avoid duplicates
                        try:
                            self.supabase.table("content_posts").delete().eq("id", temp_post_id).execute()
                            logger.info(f"Cleaned up temporary post {temp_post_id}")
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to clean up temporary post {temp_post_id}: {cleanup_error}")
                    else:
                        logger.error("Failed to create temporary post for media generation")
                        state["should_generate_media"] = False
                        state["has_media"] = False
                        
                except Exception as e:
                    logger.error(f"Error generating media: {e}")
                    # Continue without media
                    state["should_generate_media"] = False
                    state["has_media"] = False
            
            # Initialize content history if this is the first generation
            if "content_history" not in state or not state.get("content_history"):
                state["content_history"] = []
                state["current_content_version"] = 0
            
            # Add current content to history
            # Use generated_content from state (which may have been updated with media URL after generation)
            content_to_add = state.get("generated_content", content_data).copy()
            content_version = {
                "content": content_to_add,
                "version": len(state["content_history"]) + 1,
                "timestamp": datetime.now().isoformat(),
                "is_current": True
            }
            
            # Mark all previous versions as not current
            for prev_version in state["content_history"]:
                prev_version["is_current"] = False
            
            state["content_history"].append(content_version)
            state["current_content_version"] = len(state["content_history"]) - 1
            
            # Transition to preview and edit step
            state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
            state["progress_percentage"] = 85
            
            # Clear any previous error messages
            if "error_message" in state:
                del state["error_message"]
            
            # Remove the content message added earlier - preview_and_edit will add its own preview message
            # Keep only the last message if it's not a preview message
            if state["conversation_messages"]:
                last_msg = state["conversation_messages"][-1]
                if not last_msg.get("preview_mode"):
                    # Remove the last message - preview_and_edit will add a proper preview message
                    state["conversation_messages"] = state["conversation_messages"][:-1]
            
            # Go to preview and edit - this will add the preview message
            return await self.preview_and_edit(state)
            
        except Exception as e:
            logger.error(f"Critical error in generate_content: {e}")
            # Don't set to ERROR - try to continue with basic content
            # Create a basic content based on description only
            try:
                basic_content = {
                    "content": f"{user_description or 'Your content description'}",
                    "title": f"{content_type} for {platform}",
                    "hashtags": [],
                    "post_type": "carousel" if is_carousel else "text"
                }
                
                if is_carousel and carousel_images:
                    basic_content["carousel_images"] = carousel_images
                
                state["generated_content"] = basic_content
                
                message = {
                    "role": "assistant",
                    "content": f"I encountered an issue, but I've created content based on your description. Please review it below.\n\n**{basic_content['title']}**\n\n{basic_content['content']}",
                    "timestamp": datetime.now().isoformat(),
                    "carousel_images": carousel_images if is_carousel else None,
                    "structured_content": None
                }
                state["conversation_messages"].append(message)
                
                # Initialize content history if needed
                if "content_history" not in state or not state.get("content_history"):
                    state["content_history"] = []
                    state["current_content_version"] = 0
                
                # Add basic content to history
                content_version = {
                    "content": basic_content.copy(),
                    "version": len(state.get("content_history", [])) + 1,
                    "timestamp": datetime.now().isoformat(),
                    "is_current": True
                }
                if "content_history" not in state:
                    state["content_history"] = []
                state["content_history"].append(content_version)
                state["current_content_version"] = len(state["content_history"]) - 1
                
                # Continue to preview and edit step
                state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
                state["progress_percentage"] = 85
                return await self.preview_and_edit(state)
            except Exception as e2:
                logger.error(f"Failed to create basic content: {e2}")
                # Last resort - set error but don't break the flow
                state["error_message"] = f"Content generation failed: {str(e)}"
                state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
                return state
            
        except Exception as e:
            logger.error(f"Error in generate_content: {e}")
            state["error_message"] = f"Failed to generate content: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state

    async def preview_and_edit(self, state: CustomContentState) -> CustomContentState:
        """Preview content and allow real-time editing with natural language prompts"""
        try:
            # Check if user wants to edit (has edit prompt)
            if state.get("wants_to_edit", False) and state.get("edit_prompt"):
                # Apply the edit
                edit_prompt = state.get("edit_prompt", "")
                state["wants_to_edit"] = False
                state.pop("edit_prompt", None)
                return await self.apply_content_edit(state, edit_prompt)
            
            # Check if user just switched versions - refresh preview with new version
            if state.get("version_switched", False):
                state["version_switched"] = False
                state["preview_confirmed"] = False  # Reset preview confirmation after version switch
                logger.info("Version switched, refreshing preview")
            
            # Check if preview is already confirmed AND we already have a preview message - skip showing preview again
            # But if we're coming from generate_content, we need to show the preview even if preview_confirmed is False
            if state.get("preview_confirmed", False):
                # Check if there's already a preview message in the conversation
                has_preview_message = any(msg.get("preview_mode") for msg in state.get("conversation_messages", []))
                if has_preview_message:
                    logger.info("Preview already confirmed and message exists, skipping preview display")
                    return state
                # If no preview message exists, show it anyway
                logger.info("Preview confirmed but no message exists, showing preview")
            
            state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
            state["progress_percentage"] = 90
            
            # Get current content version
            content_history = state.get("content_history", [])
            current_version_index = state.get("current_content_version", len(content_history) - 1 if content_history else -1)
            
            if not content_history or current_version_index < 0 or current_version_index >= len(content_history):
                # Fallback to generated_content if history is empty
                current_content = state.get("generated_content", {})
                if not current_content:
                    state["error_message"] = "No content available to preview"
                    state["current_step"] = ConversationStep.ERROR
                    return state
            else:
                current_content = content_history[current_version_index]["content"]
            
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            
            # Get image URL for Image Post
            is_image_post = current_content.get("type") == "image_post" or content_type.lower() in ["image post", "image", "photo"]
            image_url = current_content.get("media_url") or state.get("edited_image_url") or state.get("uploaded_media_url") or state.get("generated_media_url")
            
            # Create preview message with all versions
            message = {
                "role": "assistant",
                "content": f"**Preview your {content_type} for {platform}**\n\nPreview your post and fine-tune it in real time. You can make instant changes by describing your edit in natural language.",
                "timestamp": datetime.now().isoformat(),
                "preview_mode": True,
                "current_content": current_content,
                "content_history": content_history,
                "current_version": current_version_index + 1 if current_version_index >= 0 else 1,
                "total_versions": len(content_history) if content_history else 1,
                "can_undo": current_version_index > 0,
                "options": [
                    {"value": "proceed", "label": "✅ Looks good, proceed to schedule"},
                    {"value": "edit", "label": "✏️ Edit this content"}
                ]
            }
            
            # Add image preview for Image Post
            if is_image_post and image_url:
                message["has_media"] = True
                message["media_url"] = image_url
                message["media_type"] = "image"
                message["image_post"] = True
            
            # Remove any existing preview messages to avoid duplicates
            state["conversation_messages"] = [
                msg for msg in state.get("conversation_messages", [])
                if not msg.get("preview_mode")
            ]
            
            state["conversation_messages"].append(message)
            
            logger.info(f"Showing preview for {content_type} on {platform} (version {current_version_index + 1 if current_version_index >= 0 else 1})")
            logger.info(f"Preview message added to conversation. Total messages: {len(state.get('conversation_messages', []))}")
            logger.info(f"Current step after preview: {state.get('current_step')}")
            
        except Exception as e:
            logger.error(f"Error in preview_and_edit: {e}")
            state["error_message"] = f"Failed to show preview: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def apply_content_edit(self, state: CustomContentState, edit_prompt: str) -> CustomContentState:
        """Apply edits to content based on natural language prompt"""
        try:
            # Get current content
            content_history = state.get("content_history", [])
            current_version_index = state.get("current_content_version", len(content_history) - 1 if content_history else -1)
            
            if not content_history or current_version_index < 0:
                current_content = state.get("generated_content", {})
            else:
                current_content = content_history[current_version_index]["content"]
            
            if not current_content:
                state["error_message"] = "No content available to edit"
                return state
            
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            user_description = state.get("user_description", "")
            business_context = state.get("business_context") or self._load_business_context(state["user_id"])
            
            # Check if user has uploaded media that should be preserved
            uploaded_media_url = state.get("uploaded_media_url")
            has_media = state.get("has_media", False)
            is_image_post = content_type.lower() in ["image post", "photo"]
            
            # Determine if edit is about image refinement or content refinement
            edit_lower = edit_prompt.lower()
            is_image_refinement = any(keyword in edit_lower for keyword in [
                "image", "picture", "photo", "visual", "background", "color", "brightness", 
                "filter", "crop", "sharpness", "edit image", "change image", "modify image"
            ])
            
            # Create sanitized content for editing (exclude media_url to avoid token limit)
            # Only include editable text fields
            sanitized_content = {}
            for key in ["caption", "hashtags", "call_to_action", "cta", "alt_text", "content", "title", "description"]:
                if key in current_content:
                    sanitized_content[key] = current_content[key]
            
            # Store the media_url separately to preserve it
            preserved_media_url = current_content.get("media_url") or state.get("edited_image_url") or uploaded_media_url
            
            # Create edit prompt (without media_url to avoid token limit errors)
            image_preservation_note = ""
            if is_image_post and has_media:
                image_preservation_note = """
                    
                    IMPORTANT: This is an Image Post. The media_url field will be preserved automatically.
                    You only need to edit the text fields (caption, hashtags, call_to_action, alt_text).
                    Do NOT include media_url in your response - it will be added automatically.
                    """
            
            edit_prompt_text = f"""
            The user wants to edit their {content_type} for {platform}. 
            
            Current content (text fields only):
            {json.dumps(sanitized_content, indent=2)}
            
            User's edit request: "{edit_prompt}"
            {image_preservation_note}
            Business Context:
            - Business Name: {business_context.get('business_name', 'Not specified')}
            - Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
            
            Apply the requested changes to the text fields only (caption, hashtags, call_to_action, alt_text).
            Return ONLY a valid JSON object with these fields.
            Do NOT include media_url or other non-text fields.
            Do NOT include markdown code blocks.
            """
            
            # Generate edited content
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert content editor. Apply user-requested edits to social media content while maintaining structure and quality."},
                    {"role": "user", "content": edit_prompt_text}
                ],
                temperature=0.7,
                max_tokens=1000,
                timeout=60
            )
            
            edited_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                # Try to extract JSON from markdown if present
                if "```json" in edited_text:
                    json_start = edited_text.find("```json") + 7
                    json_end = edited_text.find("```", json_start)
                    if json_end != -1:
                        edited_text = edited_text[json_start:json_end].strip()
                elif "```" in edited_text:
                    json_start = edited_text.find("```") + 3
                    json_end = edited_text.find("```", json_start)
                    if json_end != -1:
                        edited_text = edited_text[json_start:json_end].strip()
                
                # Find JSON object
                if edited_text.startswith('{') and edited_text.endswith('}'):
                    json_text = edited_text
                else:
                    start_idx = edited_text.find('{')
                    end_idx = edited_text.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_text = edited_text[start_idx:end_idx + 1]
                    else:
                        raise ValueError("No JSON found in response")
                
                edited_content = json.loads(json_text)
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse edited content: {e}")
                state["error_message"] = f"Failed to apply edit: Could not parse response"
                # Clear edit flags and return to preview mode
                state["wants_to_edit"] = False
                state.pop("edit_prompt", None)
                # Ensure we're still in preview mode to show options again
                state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
                # Show preview again with error message
                return await self.preview_and_edit(state)
            
            # Preserve media_url and other non-text fields from original content
            if preserved_media_url:
                edited_content["media_url"] = preserved_media_url
            
            # Preserve type and post_type for Image Posts
            if is_image_post:
                edited_content["post_type"] = current_content.get("post_type", "image")
                edited_content["type"] = current_content.get("type", "image_post")
            
            # Preserve any other fields that weren't edited (like structured_content, etc.)
            for key in current_content:
                if key not in ["caption", "hashtags", "call_to_action", "cta", "alt_text", "content", "title", "description"]:
                    if key not in edited_content:
                        edited_content[key] = current_content[key]
            
            logger.info(f"Applied edit: {edit_prompt}. Preserved media_url: {preserved_media_url is not None}")
            
            # Add edited version to history
            if "content_history" not in state:
                state["content_history"] = []
            
            # Mark all previous versions as not current
            for prev_version in state["content_history"]:
                prev_version["is_current"] = False
            
            # Add new version
            new_version = {
                "content": edited_content,
                "version": len(state["content_history"]) + 1,
                "timestamp": datetime.now().isoformat(),
                "is_current": True,
                "edit_prompt": edit_prompt
            }
            state["content_history"].append(new_version)
            state["current_content_version"] = len(state["content_history"]) - 1
            state["generated_content"] = edited_content
            
            # Update preview message
            return await self.preview_and_edit(state)
            
        except Exception as e:
            logger.error(f"Error applying content edit: {e}")
            state["error_message"] = f"Failed to apply edit: {str(e)}"
            # Clear edit flags and return to preview mode
            state["wants_to_edit"] = False
            state.pop("edit_prompt", None)
            # Ensure we're still in preview mode to show options again
            state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
            # Show preview again with error message
            return await self.preview_and_edit(state)

    # parse_content function removed - content is now displayed directly in chatbot
    
    
    async def _create_temp_post_for_media(self, state: CustomContentState) -> Optional[str]:
        """Create a temporary post in the database for media generation"""
        try:
            user_id = state["user_id"]
            
            # Get or create campaign for this user
            campaign_id = await self._get_or_create_custom_content_campaign(user_id)
            
            # Create temporary post data
            post_data = {
                "campaign_id": campaign_id,
                "platform": state.get("selected_platform", "social_media"),
                "post_type": state.get("selected_content_type", "post"),
                "title": f"Temp post for media generation - {state.get('selected_platform', 'social_media')}",
                "content": state.get("user_description", "Temporary content for media generation"),
                "hashtags": [],
                "scheduled_date": datetime.now().date().isoformat(),
                "scheduled_time": datetime.now().time().isoformat(),
                "status": "draft",
                "metadata": {
                    "user_id": user_id,
                    "is_temp": True,
                    "media_generation": True
                }
            }
            
            # Insert temporary post
            response = self.supabase.table("content_posts").insert(post_data).execute()
            
            if response.data and len(response.data) > 0:
                post_id = response.data[0]["id"]
                logger.info(f"Created temporary post {post_id} for media generation")
                return post_id
            else:
                logger.error("Failed to create temporary post for media generation")
                return None
                
        except Exception as e:
            logger.error(f"Error creating temporary post for media: {e}")
            return None
    
    async def _update_temp_post_with_content(self, post_id: str, generated_content: dict, state: CustomContentState) -> bool:
        """Update temporary post with generated content for media generation"""
        try:
            # Prepare updated post data with generated content
            update_data = {
                "title": generated_content.get("title", ""),
                "content": generated_content.get("content", ""),
                "hashtags": generated_content.get("hashtags", []),
                "metadata": {
                    "user_id": state["user_id"],
                    "is_temp": True,
                    "media_generation": True,
                    "generated_content": generated_content
                }
            }
            
            # Update the temporary post
            response = self.supabase.table("content_posts").update(update_data).eq("id", post_id).execute()
            
            if response.data and len(response.data) > 0:
                logger.info(f"Updated temporary post {post_id} with generated content")
                return True
            else:
                logger.error("Failed to update temporary post with generated content")
                return False
                
        except Exception as e:
            logger.error(f"Error updating temporary post with content: {e}")
            return False
    
    # optimize_content function removed - content is used as generated by AI

    async def confirm_content(self, state: CustomContentState) -> CustomContentState:
        """Ask user to confirm if the generated content is correct and should be saved"""
        try:
            # Prevent re-entry if we're already in confirm_content step with a recent message
            current_step = state.get("current_step")
            conversation_messages = state.get("conversation_messages", [])
            
            if current_step == ConversationStep.CONFIRM_CONTENT and conversation_messages:
                # Check if the last assistant message is a content review message
                for msg in reversed(conversation_messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        content = msg.get("content", "")
                        if ("Please review the content above and let me know" in content or 
                            "Please review it above and let me know if you'd like to save this post" in content):
                            # Check timestamp - if message is recent (within last 30 seconds), skip adding new one
                            msg_timestamp = msg.get("timestamp")
                            if msg_timestamp:
                                try:
                                    msg_time = datetime.fromisoformat(msg_timestamp.replace('Z', '+00:00'))
                                    now = datetime.now(msg_time.tzinfo) if msg_time.tzinfo else datetime.now()
                                    time_diff = (now - msg_time).total_seconds()
                                    if time_diff < 30:  # Message is less than 30 seconds old
                                        logger.info("Already in confirm_content step with recent message, skipping duplicate")
                                        return state
                                except Exception:
                                    # If timestamp parsing fails, continue to add message
                                    pass
                            else:
                                # No timestamp, but message exists - skip to prevent duplicate
                                logger.info("Already in confirm_content step with content review message, skipping duplicate")
                                return state
                        break  # Only check the last assistant message
            
            state["current_step"] = ConversationStep.CONFIRM_CONTENT
            state["progress_percentage"] = 90
            
            # Get the generated content details
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            has_media = state.get("has_media", False)
            
            # Get the generated content to include in the confirmation message
            generated_content = state.get("generated_content", {})
            
            # Create a message asking for content confirmation with the actual content
            confirmation_message = ""
            
            # Include the actual generated content in the confirmation message
            if generated_content:
                confirmation_message += f"\n\n### {generated_content.get('title', f'{content_type} for {platform}')}\n\n{generated_content.get('content', '')}"
                
                # Add hashtags if available
                if generated_content.get('hashtags'):
                    hashtags = ' '.join([f"#{tag.replace('#', '')}" for tag in generated_content['hashtags']])
                    confirmation_message += f"\n\n**{hashtags}**"
                
                # Add call to action if available
                if generated_content.get('call_to_action'):
                    confirmation_message += f"\n\n### Call to Action\n\n{generated_content['call_to_action']}"
            
            confirmation_message += "\n\n---\n\n**Please review the content above and let me know:**"
            
            # Get carousel images if this is a carousel post
            carousel_images = []
            is_carousel = content_type and content_type.lower() == "carousel"
            if is_carousel:
                carousel_image_source = state.get("carousel_image_source", "")
                if carousel_image_source == "ai_generate":
                    # Get AI-generated carousel images
                    carousel_images_data = state.get("carousel_images", [])
                    if carousel_images_data:
                        carousel_images = [img.get("url") for img in carousel_images_data if img.get("url")]
                elif carousel_image_source == "manual_upload":
                    # Get manually uploaded carousel images
                    carousel_images = state.get("uploaded_carousel_images") or []
                    if not isinstance(carousel_images, list):
                        carousel_images = []
            
            # Check if a content review message already exists to prevent duplicates
            # Check both by message content and by checking if we're already in confirm_content step with a recent message
            existing_content_review_message = None
            conversation_messages = state.get("conversation_messages", [])
            
            # First, remove any existing content review messages to ensure only one exists
            filtered_messages = []
            for msg in conversation_messages:
                if (msg.get("role") == "assistant" and 
                    msg.get("content") and 
                    ("Please review the content above and let me know" in msg.get("content") or 
                     "Please review it above and let me know if you'd like to save this post" in msg.get("content"))):
                    # Skip this message - it's a duplicate content review
                    if not existing_content_review_message:
                        existing_content_review_message = msg
                    continue
                filtered_messages.append(msg)
            
            # Update conversation messages to remove duplicates
            state["conversation_messages"] = filtered_messages
            
            # Always add the new message after cleaning up old ones
            # The cleanup already happened above, so we should always add the fresh message
            message = {
                "role": "assistant",
                "content": confirmation_message,
                "timestamp": datetime.now().isoformat(),
                "has_media": has_media or (is_carousel and len(carousel_images) > 0),
                "media_url": state.get("uploaded_media_url") or state.get("generated_media_url") if not is_carousel else None,
                "media_type": state.get("media_type") if not is_carousel else None,
                # Include carousel images in the message
                "carousel_images": carousel_images if is_carousel else None,
                # Explicitly set structured_content to null to prevent frontend from creating cards
                "structured_content": None
            }
            state["conversation_messages"].append(message)
            if existing_content_review_message:
                logger.info(f"Removed {len(conversation_messages) - len(filtered_messages)} duplicate content review message(s) and added new one")
            else:
                logger.info("Asking user to confirm generated content")
            
        except Exception as e:
            logger.error(f"Error in confirm_content: {e}")
            state["error_message"] = f"Failed to confirm content: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state

    async def select_schedule(self, state: CustomContentState) -> CustomContentState:
        """Ask user to select date and time for the post"""
        try:
            state["current_step"] = ConversationStep.SELECT_SCHEDULE
            state["progress_percentage"] = 98
            
            # Don't add any message - let the UI handle the schedule selection directly
            logger.info("Schedule selection step - UI will handle display")
            
            logger.info(f"Current state step: {state.get('current_step')}")
            logger.info(f"User input in state: {state.get('user_input')}")
            
        except Exception as e:
            logger.error(f"Error in select_schedule: {e}")
            state["error_message"] = f"Failed to select schedule: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state

    async def save_content(self, state: CustomContentState) -> CustomContentState:
        """Save the generated content to Supabase"""
        try:
            state["current_step"] = ConversationStep.SAVE_CONTENT
            state["progress_percentage"] = 95
            
            user_id = state["user_id"]
            platform = state["selected_platform"]
            content_type = state["selected_content_type"]
            
            # Get generated content from state - use the CURRENT selected version
            # Only the version marked as is_current will be saved to Supabase
            # Other versions remain in cache (content_history) but are not persisted
            content_history = state.get("content_history", [])
            current_version_index = state.get("current_content_version", len(content_history) - 1 if content_history else -1)
            
            # If we have content history, use the current version from history
            if content_history and current_version_index >= 0 and current_version_index < len(content_history):
                current_version = content_history[current_version_index]
                generated_content = current_version.get("content", {}).copy()
                logger.info(f"💾 Saving version {current_version.get('version', current_version_index + 1)} to Supabase (other {len(content_history) - 1} versions remain in cache)")
            else:
                # Fallback to generated_content if no history
                generated_content = state.get("generated_content", {}).copy()
                logger.info("💾 Saving content from generated_content (no version history)")
            
            if not generated_content:
                state["error_message"] = "No content available to save"
                state["current_step"] = ConversationStep.ERROR
                return state
            
            # Check if this is a carousel post
            is_carousel = content_type and content_type.lower() == "carousel"
            
            if is_carousel:
                # Handle carousel post
                carousel_images = state.get("carousel_images") or []
                uploaded_carousel_images = state.get("uploaded_carousel_images") or []
                
                # Combine AI-generated and manually uploaded images
                all_carousel_images = []
                for img in carousel_images:
                    if img.get("url"):
                        all_carousel_images.append(img.get("url"))
                all_carousel_images.extend(uploaded_carousel_images)
                
                if not all_carousel_images:
                    raise Exception("Carousel post must have at least one image")
                
                # Get scheduled time
                scheduled_for = state.get("scheduled_for")
                if scheduled_for:
                    scheduled_datetime = datetime.fromisoformat(scheduled_for.replace('Z', '+00:00'))
                    # Remove timezone info for comparison with timezone-naive datetime.now()
                    if scheduled_datetime.tzinfo:
                        scheduled_datetime = scheduled_datetime.replace(tzinfo=None)
                    status = "scheduled" if scheduled_datetime > datetime.now() else "draft"
                else:
                    scheduled_datetime = datetime.now()
                    status = "draft"
                
                # Get or create campaign
                campaign_id = await self._get_or_create_custom_content_campaign(user_id)
                
                # Create carousel post data
                post_data = {
                    "campaign_id": campaign_id,
                    "platform": platform,
                    "post_type": "carousel",
                    "title": generated_content.get("title", ""),
                    "content": generated_content.get("content", ""),
                    "hashtags": generated_content.get("hashtags", []),
                    "scheduled_date": scheduled_datetime.date().isoformat(),
                    "scheduled_time": scheduled_datetime.time().isoformat(),
                    "status": status,
                    "metadata": {
                        "generated_by": "custom_content_agent",
                        "conversation_id": state["conversation_id"],
                        "user_id": user_id,
                        "platform_optimized": True,
                        "carousel_images": all_carousel_images,
                        "total_images": len(all_carousel_images),
                        "carousel_image_source": state.get("carousel_image_source", "mixed"),
                        "call_to_action": generated_content.get("call_to_action", ""),
                        "engagement_hooks": generated_content.get("engagement_hooks", ""),
                        "image_caption": generated_content.get("image_caption", ""),
                        "visual_elements": generated_content.get("visual_elements", [])
                    }
                }
                
                # Use first image as primary for preview
                if all_carousel_images:
                    post_data["primary_image_url"] = all_carousel_images[0]
                
                # Validate status matches scheduled time
                now = datetime.now()
                if scheduled_datetime > now:
                    if status != "scheduled":
                        logger.warning(f"Status mismatch: scheduled_datetime is in future but status is '{status}'. Correcting to 'scheduled'.")
                        status = "scheduled"
                        post_data["status"] = "scheduled"
                else:
                    if status != "draft":
                        logger.warning(f"Status mismatch: scheduled_datetime is not in future but status is '{status}'. Correcting to 'draft'.")
                        status = "draft"
                        post_data["status"] = "draft"
                
                # Save to Supabase
                logger.info(f"Saving carousel post to database: {post_data}")
                result = self.supabase.table("content_posts").insert(post_data).execute()
                
                if result.data:
                    post_id = result.data[0]["id"]
                    final_post_data = result.data[0]
                    # Add carousel_images at top level for easier frontend access
                    final_post_data["carousel_images"] = all_carousel_images
                    state["final_post"] = final_post_data
                    
                    # Save each carousel image to content_images table with image_order
                    for idx, image_url in enumerate(all_carousel_images):
                        try:
                            # Determine prompt based on source
                            image_prompt = "User uploaded image for carousel"
                            if idx < len(carousel_images) and carousel_images[idx].get("prompt"):
                                image_prompt = carousel_images[idx].get("prompt", "AI generated image for carousel")
                            
                            image_data = {
                                "post_id": post_id,
                                "image_url": image_url,
                                "image_prompt": image_prompt,
                                "image_style": "carousel",
                                "image_size": "custom",
                                "image_quality": "custom",
                                "generation_model": "gemini" if idx < len(carousel_images) else "user_upload",
                                "generation_service": "gemini" if idx < len(carousel_images) else "user_upload",
                                "generation_cost": 0,
                                "generation_time": 0,
                                "is_approved": True
                            }
                            
                            # Try to add image_order if column exists (some schemas may not have it)
                            # Store order in metadata instead if column doesn't exist
                            try:
                                # First try without image_order
                                insert_data = image_data.copy()
                                self.supabase.table("content_images").insert(insert_data).execute()
                            except Exception as order_error:
                                # If that fails, try with image_order (in case column exists but other field is wrong)
                                try:
                                    image_data["image_order"] = idx
                                    self.supabase.table("content_images").insert(image_data).execute()
                                except:
                                    # If both fail, log but continue - images are already in metadata
                                    logger.warning(f"Could not save image {idx + 1} to content_images, but image is in post metadata")
                                    pass
                            logger.info(f"Carousel image {idx + 1} saved to content_images for post {post_id}")
                        except Exception as e:
                            logger.error(f"Failed to save carousel image {idx + 1} to content_images: {e}")
                            # Continue even if one image save fails
                    
                    # Don't add a message here - ask_another_content will handle it
                    # Just transition to ask_another_content step
                    state["current_step"] = ConversationStep.ASK_ANOTHER_CONTENT
                    state["progress_percentage"] = 100
                    # Don't set is_complete yet - wait for user response in ask_another_content
                else:
                    raise Exception("Failed to save carousel post to database")
                
                # Register with scheduler if post is scheduled
                if status == "scheduled":
                    try:
                        from scheduler.post_publisher import post_publisher
                        if post_publisher:
                            scheduled_at = scheduled_datetime.isoformat()
                            await post_publisher.register_scheduled_post(
                                post_id,
                                scheduled_at,
                                platform,
                                user_id
                            )
                            logger.info(f"Registered scheduled carousel post {post_id} with scheduler")
                    except Exception as e:
                        logger.warning(f"Failed to register carousel post with scheduler: {e}")
                        # Don't fail the save operation if registration fails
                
                logger.info(f"Carousel post saved for user {user_id} on {platform}, post_id: {post_id}")
                return state
            
            # Regular (non-carousel) post handling
            uploaded_media_url = state.get("uploaded_media_url")
            
            # Determine final media URL (edited, uploaded, or generated)
            final_media_url = None
            uploaded_media_url = state.get("uploaded_media_url", "")
            generated_media_url = state.get("generated_media_url", "")
            edited_media_url = state.get("edited_image_url", "")  # Edited image takes priority
            
            # Priority: edited > generated > uploaded
            if edited_media_url:
                final_media_url = edited_media_url
                logger.info(f"Using edited image URL: {final_media_url}")
            elif generated_media_url:
                final_media_url = generated_media_url
                logger.info(f"Using generated media URL: {final_media_url}")
            elif uploaded_media_url and uploaded_media_url.startswith("data:"):
                try:
                    final_media_url = await self._upload_base64_image_to_supabase(
                        uploaded_media_url, user_id, platform
                    )
                    logger.info(f"Image uploaded to Supabase: {final_media_url}")
                except Exception as e:
                    logger.error(f"Failed to upload image to Supabase: {e}")
                    # Continue without image if upload fails
                    final_media_url = None
            elif uploaded_media_url:
                # Already uploaded image URL
                final_media_url = uploaded_media_url
                logger.info(f"Using existing uploaded media URL: {final_media_url}")
            
            # Get scheduled time
            scheduled_for = state.get("scheduled_for")
            if scheduled_for:
                # Parse the scheduled time
                scheduled_datetime = datetime.fromisoformat(scheduled_for.replace('Z', '+00:00'))
                # Remove timezone info for comparison with timezone-naive datetime.now()
                if scheduled_datetime.tzinfo:
                    scheduled_datetime = scheduled_datetime.replace(tzinfo=None)
                status = "scheduled" if scheduled_datetime > datetime.now() else "draft"
            else:
                scheduled_datetime = datetime.now()
                status = "draft"
            
            # Get or create a default campaign for custom content
            campaign_id = await self._get_or_create_custom_content_campaign(user_id)
            
            # Determine post_type: if video is uploaded, set post_type to "video"
            media_type = state.get("media_type", "")
            # Handle both enum and string values
            media_type_str = str(media_type).lower() if media_type else ""
            if media_type_str == "video" or media_type == MediaType.VIDEO:
                post_type = "video"
            elif media_type_str == "image" or media_type == MediaType.IMAGE:
                # Only override if content_type is not already image-specific
                if content_type and content_type.lower() not in ["image", "video", "carousel"]:
                    post_type = "image"
                else:
                    post_type = content_type
            else:
                post_type = content_type
            
            # Handle Image Post structure (caption, hashtags, CTA)
            is_image_post = generated_content.get("type") == "image_post" or content_type.lower() in ["image post", "image", "photo"]
            
            if is_image_post:
                # Image Post: use caption instead of content
                post_content = generated_content.get("caption", generated_content.get("content", ""))
            else:
                # Regular post: use content
                post_content = generated_content.get("content", "")
            
            # Create post data for content_posts table
            post_data = {
                "campaign_id": campaign_id,  # Use the custom content campaign
                "platform": platform,
                "post_type": "image" if is_image_post else post_type,
                "title": generated_content.get("title", ""),
                "content": post_content,
                "hashtags": generated_content.get("hashtags", []),
                "scheduled_date": scheduled_datetime.date().isoformat(),
                "scheduled_time": scheduled_datetime.time().isoformat(),
                "status": status,
                "metadata": {
                    "generated_by": "custom_content_agent",
                    "conversation_id": state["conversation_id"],
                    "user_id": user_id,
                    "platform_optimized": True,
                    "has_media": bool(final_media_url),
                    "media_url": final_media_url,
                    "media_type": state.get("media_type", ""),
                    "original_media_filename": state.get("uploaded_media_filename", ""),
                    "media_size": state.get("uploaded_media_size", 0),
                    "call_to_action": generated_content.get("call_to_action", ""),
                    "engagement_hooks": generated_content.get("engagement_hooks", ""),
                    "image_caption": generated_content.get("image_caption", ""),
                    "visual_elements": generated_content.get("visual_elements", [])
                }
            }
            
            # Add primary image data to post_data if image exists
            if final_media_url:
                # Determine image prompt based on source
                image_prompt = "User uploaded image for custom content"
                if generated_media_url:
                    # Try to get prompt from state if it was generated
                    image_prompt = state.get("generated_image_prompt", "AI generated image for custom content")
                
                post_data["primary_image_url"] = final_media_url
                post_data["primary_image_prompt"] = image_prompt
                post_data["primary_image_approved"] = True  # User uploads/generated images in custom content are auto-approved
                
                # For Image Post, also store alt text
                if is_image_post and generated_content.get("alt_text"):
                    post_data["metadata"]["alt_text"] = generated_content.get("alt_text")
                elif state.get("image_edit_type"):
                    # Image was edited
                    edit_type = state.get("image_edit_type", "")
                    image_prompt = f"User uploaded image edited with {edit_type.replace('_', ' ')}"
                    post_data["primary_image_prompt"] = image_prompt
            
            # Validate status matches scheduled time
            now = datetime.now()
            if scheduled_datetime > now:
                if status != "scheduled":
                    logger.warning(f"Status mismatch: scheduled_datetime is in future but status is '{status}'. Correcting to 'scheduled'.")
                    status = "scheduled"
                    post_data["status"] = "scheduled"
            else:
                if status != "draft":
                    logger.warning(f"Status mismatch: scheduled_datetime is not in future but status is '{status}'. Correcting to 'draft'.")
                    status = "draft"
                    post_data["status"] = "draft"
            
            # Save to Supabase
            logger.info(f"Saving post to database: {post_data}")
            result = self.supabase.table("content_posts").insert(post_data).execute()
            
            if result.data:
                post_id = result.data[0]["id"]
                state["final_post"] = result.data[0]
                
                # Also save image metadata to content_images table (temporary - for migration period)
                if final_media_url:
                    try:
                        image_data = {
                            "post_id": post_id,
                            "image_url": final_media_url,
                            "image_prompt": post_data.get("primary_image_prompt", "User uploaded image for custom content"),
                            "image_style": "user_upload",
                            "image_size": "custom",
                            "image_quality": "custom",
                            "generation_model": "user_upload",
                            "generation_service": "user_upload",
                            "generation_cost": 0,
                            "generation_time": 0,
                            "is_approved": True
                        }
                        
                        self.supabase.table("content_images").insert(image_data).execute()
                        logger.info(f"Image metadata saved to content_images for post {post_id}")
                    except Exception as e:
                        logger.error(f"Failed to save image metadata to content_images: {e}")
                        # Continue even if image metadata save fails
                
                # Determine if image was uploaded or generated
                image_source = "generated" if generated_media_url else "uploaded"
                
                # Don't add a message here - ask_another_content will handle it
                # Just transition to ask_another_content step
                state["current_step"] = ConversationStep.ASK_ANOTHER_CONTENT
                state["progress_percentage"] = 100
                # Don't set is_complete yet - wait for user response in ask_another_content
            else:
                raise Exception("Failed to save content to database")
            
            # Register with scheduler if post is scheduled
            if status == "scheduled":
                try:
                    from scheduler.post_publisher import post_publisher
                    if post_publisher:
                        scheduled_at = scheduled_datetime.isoformat()
                        await post_publisher.register_scheduled_post(
                            post_id,
                            scheduled_at,
                            platform,
                            user_id
                        )
                        logger.info(f"Registered scheduled post {post_id} with scheduler")
                except Exception as e:
                    logger.warning(f"Failed to register post with scheduler: {e}")
                    # Don't fail the save operation if registration fails
            
            logger.info(f"Content saved for user {user_id} on {platform}, post_id: {post_id}")
            
        except Exception as e:
            logger.error(f"Error in save_content: {e}")
            state["error_message"] = f"Failed to save content: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def ask_another_content(self, state: CustomContentState) -> CustomContentState:
        """Ask if user wants to generate another content after scheduling"""
        try:
            state["current_step"] = ConversationStep.ASK_ANOTHER_CONTENT
            logger.info("Asking if user wants to generate another content")
            
            # Only add the message if we haven't already asked about another content
            # Check if the last message is already asking about another content
            last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
            another_content_message = "Your post has been saved to the schedule section! 🎉\n\nWant to create another post or are you done for now?"
            
            if not last_message or another_content_message not in last_message.get("content", ""):
                # Add the question message with options
                message = {
                    "role": "assistant",
                    "content": another_content_message,
                    "timestamp": datetime.now().isoformat(),
                    "options": [
                        {"value": "yes", "label": "Create another post"},
                        {"value": "no", "label": "I'm done for now"}
                    ]
                }
                state["conversation_messages"].append(message)
                logger.info("Added ask another content message")
            else:
                logger.info("Ask another content message already present, skipping duplicate")
            
            return state
            
        except Exception as e:
            logger.error(f"Error in ask_another_content: {e}")
            state["error_message"] = f"Failed to ask about another content: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
    
    async def _generate_image_post_content(self, state: CustomContentState, image_url: str, user_description: str, platform: str, content_type: str) -> CustomContentState:
        """Generate short caption, hashtags, and CTA for Image Post only"""
        try:
            # Load business context
            business_context = state.get("business_context")
            if not business_context:
                user_id = state.get("user_id")
                if user_id:
                    business_context = self._load_business_context(user_id)
                    state["business_context"] = business_context
                else:
                    business_context = {}
            
            # Analyze image
            image_analysis = ""
            try:
                image_analysis = await self._analyze_uploaded_image(image_url, user_description, business_context)
                logger.info("Image analysis completed for Image Post")
            except Exception as e:
                logger.error(f"Image analysis failed: {e}")
                image_analysis = f"Image analysis failed: {str(e)}"
            
            # Create prompt for SHORT caption only (not long content)
            prompt = f"""
            Create a SHORT, engaging Instagram-style caption for an Image Post on {platform}.
            
            User's description: "{user_description}"
            
            Image Analysis:
            {image_analysis if image_analysis else "No image analysis available"}
            
            Business Context:
            - Business Name: {business_context.get('business_name', 'Not specified')}
            - Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
            
            Requirements:
            - Generate ONLY a short, punchy caption (1-2 sentences max, ~125 characters ideal for Instagram)
            - Include relevant hashtags (platform-appropriate count)
            - Add a compelling call-to-action (CTA)
            - Include alt text for accessibility
            
            CRITICAL: Return ONLY a valid JSON object. Do NOT use markdown code blocks.
            
            {{
              "caption": "Short, engaging caption here",
              "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
              "call_to_action": "Compelling CTA",
              "alt_text": "Accessibility description of the image"
            }}
            """
            
            # Generate content with image
            # Try to download image and use base64 if URL fails
            import base64
            import httpx
            
            image_for_api = image_url
            try:
                # Try downloading the image to use base64 (more reliable than URL)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    img_response = await client.get(image_url)
                    img_response.raise_for_status()
                    img_data = img_response.content
                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                    # Determine format from HTTP content-type header
                    http_content_type = img_response.headers.get('content-type', 'image/jpeg')
                    if 'png' in http_content_type:
                        img_format = 'png'
                    elif 'jpeg' in http_content_type or 'jpg' in http_content_type:
                        img_format = 'jpeg'
                    else:
                        img_format = 'jpeg'
                    image_for_api = f"data:image/{img_format};base64,{img_base64}"
                    logger.info(f"Downloaded image for OpenAI API: {len(img_data)} bytes")
            except Exception as download_err:
                logger.warning(f"Could not download image for API, using URL: {download_err}")
                # Will try URL, but might timeout
                image_for_api = image_url
            
            messages = [
                {"role": "system", "content": "You are an expert social media content creator. Generate SHORT, engaging captions for image posts. Return ONLY valid JSON, no markdown."},
                {"role": "user", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Here's the image for this post:"},
                        {"type": "image_url", "image_url": {"url": image_for_api}}
                    ]
                }
            ]
            
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=500,  # Shorter for caption only
                    timeout=60
                )
                generated_text = response.choices[0].message.content.strip()
            except Exception as api_error:
                logger.warning(f"OpenAI API error for content generation: {api_error}")
                # Continue without API - use fallback content based on user description
                logger.info("Using fallback content generation without image analysis")
                generated_text = None
            
            # Parse JSON or use fallback
            if generated_text:
                try:
                    if "```json" in generated_text:
                        json_start = generated_text.find("```json") + 7
                        json_end = generated_text.find("```", json_start)
                        if json_end != -1:
                            generated_text = generated_text[json_start:json_end].strip()
                    elif "```" in generated_text:
                        json_start = generated_text.find("```") + 3
                        json_end = generated_text.find("```", json_start)
                        if json_end != -1:
                            generated_text = generated_text[json_start:json_end].strip()
                    
                    if generated_text.startswith('{') and generated_text.endswith('}'):
                        json_text = generated_text
                    else:
                        start_idx = generated_text.find('{')
                        end_idx = generated_text.rfind('}')
                        if start_idx != -1 and end_idx != -1:
                            json_text = generated_text[start_idx:end_idx + 1]
                        else:
                            raise ValueError("No JSON found")
                    
                    content_data = json.loads(json_text)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse Image Post content: {e}, using fallback")
                    # Fallback
                    content_data = {
                        "caption": user_description[:125] if len(user_description) > 125 else user_description,
                        "hashtags": self._extract_hashtags(user_description),
                        "call_to_action": "Check it out!",
                        "alt_text": "Social media post image"
                    }
            else:
                # No API response - use fallback
                logger.info("No API response, using fallback content")
                content_data = {
                    "caption": user_description[:125] if len(user_description) > 125 else user_description,
                    "hashtags": self._extract_hashtags(user_description),
                    "call_to_action": "Check it out!",
                    "alt_text": "Social media post image"
                }
            
            # Structure as Image Post
            content_data["type"] = "image_post"
            # Use edited image URL if available, otherwise the provided image_url
            final_image_url = state.get("edited_image_url") or image_url
            content_data["media_url"] = final_image_url
            content_data["post_type"] = "image"
            
            state["generated_content"] = content_data
            
            # Use edited image URL if available
            final_image_url = state.get("edited_image_url") or image_url
            
            # Initialize content history if this is the first generation
            if "content_history" not in state or not state.get("content_history"):
                state["content_history"] = []
                state["current_content_version"] = 0
            
            # Add current content to history
            content_version = {
                "content": content_data.copy(),
                "version": len(state["content_history"]) + 1,
                "timestamp": datetime.now().isoformat(),
                "is_current": True
            }
            
            # Mark all previous versions as not current
            for prev_version in state["content_history"]:
                prev_version["is_current"] = False
            
            state["content_history"].append(content_version)
            state["current_content_version"] = len(state["content_history"]) - 1
            
            # DO NOT add preview message here - let preview_and_edit add it with proper structure
            # This ensures the preview message has all required fields (options, etc.)
            
            logger.info(f"Generated Image Post content for {platform}")
            
            # Transition to preview_and_edit
            state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
            state["progress_percentage"] = 85
            
            return state
            
        except Exception as e:
            logger.error(f"Error generating Image Post content: {e}")
            # Don't set ERROR state - use fallback content instead
            logger.info("Using fallback content due to error")
            try:
                # Get user description from state if not in scope
                user_desc = state.get("user_description", user_description if 'user_description' in locals() else "Image post")
                
                # Create fallback content
                content_data = {
                    "caption": user_desc[:125] if len(user_desc) > 125 else user_desc,
                    "hashtags": self._extract_hashtags(user_desc),
                    "call_to_action": "Check it out!",
                    "alt_text": "Social media post image",
                    "type": "image_post",
                    "media_url": state.get("edited_image_url") or image_url,
                    "post_type": "image"
                }
                state["generated_content"] = content_data
                
                # Create message
                hashtags_text = ' '.join([f"#{tag.replace('#', '')}" for tag in content_data.get('hashtags', [])])
                message_content = f"Perfect! I've created your Image Post caption:\n\n**Caption:**\n{content_data.get('caption', '')}\n\n**Hashtags:**\n{hashtags_text}\n\n**Call to Action:**\n{content_data.get('call_to_action', '')}"
                
                final_image_url = state.get("edited_image_url") or image_url
                message = {
                    "role": "assistant",
                    "content": message_content,
                    "timestamp": datetime.now().isoformat(),
                    "has_media": True,
                    "media_url": final_image_url,
                    "media_type": "image",
                    "structured_content": None,
                    "image_post": True
                }
                state["conversation_messages"].append(message)
                
                # Transition to preview_and_edit
                state["current_step"] = ConversationStep.PREVIEW_AND_EDIT
                logger.info("Generated fallback Image Post content")
            except Exception as fallback_error:
                logger.error(f"Even fallback failed: {fallback_error}")
                state["error_message"] = f"Failed to generate Image Post content: {str(e)}"
                state["current_step"] = ConversationStep.ERROR
            return state
    
    async def generate_edited_image_with_prompt(self, state: CustomContentState, edit_prompt: str) -> CustomContentState:
        """Generate edited image using AI based on natural language prompt"""
        try:
            import google.generativeai as genai
            import base64
            import httpx
            import uuid
            
            image_url = state.get("uploaded_media_url") or state.get("generated_media_url")
            if not image_url:
                state["error_message"] = "No image available to edit"
                return state
            
            user_id = state.get("user_id")
            platform = state.get("selected_platform", "social_media")
            
            # Handle base64 data URLs (data:image/...) - these are too long to download
            if image_url.startswith("data:image/"):
                # Extract base64 data from data URL
                try:
                    # Format: data:image/jpeg;base64,<base64_data>
                    header, base64_data = image_url.split(",", 1)
                    # Decode base64 to get image bytes, then re-encode for Gemini
                    image_data = base64.b64decode(base64_data)
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"Extracted image from base64 data URL: {len(image_data)} bytes")
                except Exception as e:
                    logger.error(f"Failed to parse base64 data URL: {e}")
                    state["error_message"] = f"Failed to process image: {str(e)}"
                    return state
            else:
                # Download original image from URL
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        image_response = await client.get(image_url)
                        image_response.raise_for_status()
                        image_data = image_response.content
                    
                    # Convert to base64
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"Downloaded image from URL: {len(image_data)} bytes")
                except Exception as e:
                    error_str = str(e)
                    if "URL too long" in error_str or "too long" in error_str.lower():
                        logger.error(f"Image URL is too long to download: {len(image_url)} characters")
                        state["error_message"] = "Image URL is too long. Please try uploading the image again or use a different image."
                    else:
                        logger.error(f"Failed to download image: {e}")
                        state["error_message"] = f"Failed to download image: {str(e)}"
                    return state
            
            # Create comprehensive edit prompt
            full_prompt = f"""Edit this image according to the following instructions: {edit_prompt}

IMPORTANT REQUIREMENTS:
- Maintain the overall composition and quality
- Apply the requested changes precisely
- Preserve image quality and resolution
- Return the edited image, not a text description
- Ensure the edited image matches the original dimensions and aspect ratio

OUTPUT: Return only the edited image."""
            
            # Initialize Gemini
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                state["error_message"] = "Image editing not available - GEMINI_API_KEY not set"
                return state
            
            # Configure Gemini API (matching media_agent pattern)
            genai.configure(api_key=gemini_api_key)
            gemini_model = 'gemini-2.5-flash-image-preview'
            
            # Create contents for Gemini
            contents = [
                {"text": full_prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
            
            # Generate edited image using Gemini
            logger.info(f"Calling Gemini model: {gemini_model} for image editing")
            logger.info(f"Edit prompt: {edit_prompt[:100]}...")
            logger.info(f"Image size: {len(image_data)} bytes")
            
            try:
                response = genai.GenerativeModel(gemini_model).generate_content(
                    contents=contents,
                )
                
                logger.info(f"Gemini response received: {len(response.candidates) if response.candidates else 0} candidates")
                
                # Extract image from response
                if not response.candidates or not response.candidates[0].content:
                    raise Exception("No image returned from Gemini - no candidates in response")
                
                edited_image_data = None
                candidate = response.candidates[0]
                
                # Check all parts for image data
                for i, part in enumerate(candidate.content.parts):
                    logger.info(f"Checking part {i}: inline_data={part.inline_data is not None if hasattr(part, 'inline_data') else False}")
                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                        # Gemini may return bytes or base64 string
                        image_data_raw = part.inline_data.data
                        if isinstance(image_data_raw, bytes):
                            edited_image_data = image_data_raw
                        else:
                            # If it's base64 string, decode it
                            edited_image_data = base64.b64decode(image_data_raw)
                        logger.info(f"Found image data in part {i}: {len(edited_image_data)} bytes")
                        break
                    elif hasattr(part, 'text') and part.text:
                        logger.warning(f"Part {i} contains text instead of image: {part.text[:200]}...")
                
                if not edited_image_data:
                    # Try to get text response for debugging
                    text_content = ""
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_content += part.text
                    logger.error(f"No image data found. Gemini text response: {text_content[:500]}...")
                    raise Exception(f"No image data in Gemini response. Response: {text_content[:200]}")
                    
            except Exception as gemini_error:
                error_str = str(gemini_error)
                logger.error(f"Gemini API error: {error_str}")
                
                # Check for specific error types
                if "API key" in error_str.lower() or "authentication" in error_str.lower():
                    state["error_message"] = "Gemini API authentication failed. Please check GEMINI_API_KEY."
                    return state
                elif "quota" in error_str.lower() or "limit" in error_str.lower():
                    state["error_message"] = "Gemini API quota exceeded. Please try again later."
                    return state
                else:
                    state["error_message"] = f"Failed to edit image with Gemini: {error_str}"
                    return state
            
            # Upload edited image to Supabase
            filename = f"custom_content_{user_id}_{platform}_{uuid.uuid4().hex[:8]}_edited.jpg"
            bucket_name = "user-uploads"
            
            storage_response = self.supabase.storage.from_(bucket_name).upload(
                filename,
                edited_image_data,
                file_options={"content-type": "image/jpeg"}
            )
            
            if hasattr(storage_response, 'error') and storage_response.error:
                raise Exception(f"Storage upload failed: {storage_response.error}")
            
            edited_image_url = self.supabase.storage.from_(bucket_name).get_public_url(filename)
            
            # Update state with edited image (preserve original URL)
            original_url = state.get("uploaded_media_url") or state.get("generated_media_url")
            state["edited_image_url"] = edited_image_url
            state["image_edit_type"] = "custom_edit"
            
            # Store original URL for version comparison
            if not state.get("original_image_url"):
                state["original_image_url"] = original_url
            
            logger.info(f"Successfully generated and uploaded edited image: {edited_image_url}")
            
            # Initialize content history if needed
            if "content_history" not in state:
                state["content_history"] = []
            
            # Create a version entry for the edited image
            version_number = len(state["content_history"]) + 1
            edited_version = {
                "content": {
                    "type": "image_post",
                    "media_url": edited_image_url,
                    "original_media_url": original_url,
                    "edit_prompt": edit_prompt,
                    "is_edited": True
                },
                "version": version_number,
                "timestamp": datetime.now().isoformat(),
                "is_current": True
            }
            # Mark previous versions as not current
            for prev_version in state["content_history"]:
                prev_version["is_current"] = False
            state["content_history"].append(edited_version)
            state["current_content_version"] = len(state["content_history"]) - 1
            
            # Add success message showing edited version
            message = {
                "role": "assistant",
                "content": f"✅ Image edited successfully! Here's version {version_number} of your image:\n\n**Edit applied:** {edit_prompt}\n\nYou can continue editing or proceed to generate the caption.",
                "timestamp": datetime.now().isoformat(),
                "has_media": True,
                "media_url": edited_image_url,
                "media_type": "image",
                "original_image_url": original_url,  # Show original for comparison
                "is_edited_version": True,
                "edit_prompt": edit_prompt,
                "version_number": version_number
            }
            state["conversation_messages"].append(message)
            
            return state
            
        except Exception as e:
            logger.error(f"Error generating edited image with prompt: {e}")
            state["error_message"] = f"Failed to edit image: {str(e)}"
            return state
    
    async def generate_edited_image(self, state: CustomContentState, edit_type: str, edit_instructions: str = "") -> CustomContentState:
        """Generate edited image using AI based on edit type and instructions"""
        try:
            import google.generativeai as genai
            import base64
            import httpx
            import uuid
            
            image_url = state.get("uploaded_media_url") or state.get("generated_media_url")
            if not image_url:
                state["error_message"] = "No image available to edit"
                return state
            
            user_id = state.get("user_id")
            platform = state.get("selected_platform", "social_media")
            
            # Handle base64 data URLs (data:image/...) - these are too long to download
            if image_url.startswith("data:image/"):
                # Extract base64 data from data URL
                try:
                    # Format: data:image/jpeg;base64,<base64_data>
                    header, base64_data = image_url.split(",", 1)
                    # Decode base64 to get image bytes, then re-encode for Gemini
                    image_data = base64.b64decode(base64_data)
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"Extracted image from base64 data URL: {len(image_data)} bytes")
                except Exception as e:
                    logger.error(f"Failed to parse base64 data URL: {e}")
                    state["error_message"] = f"Failed to process image: {str(e)}"
                    return state
            else:
                # Download original image from URL
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        image_response = await client.get(image_url)
                        image_response.raise_for_status()
                        image_data = image_response.content
                    
                    # Convert to base64
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"Downloaded image from URL: {len(image_data)} bytes")
                except Exception as e:
                    error_str = str(e)
                    if "URL too long" in error_str or "too long" in error_str.lower():
                        logger.error(f"Image URL is too long to download: {len(image_url)} characters")
                        state["error_message"] = "Image URL is too long. Please try uploading the image again or use a different image."
                    else:
                        logger.error(f"Failed to download image: {e}")
                        state["error_message"] = f"Failed to download image: {str(e)}"
                    return state
            
            # Create edit prompt based on edit type
            edit_prompts = {
                "enhance": "Enhance this image: improve sharpness, clarity, and overall quality while maintaining the original composition and colors.",
                "cleanup": "Clean up this image: remove noise, artifacts, and imperfections while preserving all important details.",
                "remove_background": "Remove the background from this image, keeping only the main subject with a transparent background.",
                "change_background": f"Change the background of this image. {edit_instructions if edit_instructions else 'Use a clean, professional background that complements the main subject.'}",
                "color_correction": "Apply professional color correction: adjust brightness, contrast, saturation, and white balance for optimal visual appeal.",
                "add_filter": f"Apply a professional filter to this image. {edit_instructions if edit_instructions else 'Enhance the mood and style while maintaining natural appearance.'}",
                "crop": f"Crop this image. {edit_instructions if edit_instructions else 'Use optimal composition and framing.'}",
                "revisualize": f"Recreate this image with improvements. {edit_instructions if edit_instructions else 'Maintain the core subject and composition while enhancing visual quality.'}",
                "sharpen": "Sharpen this image: enhance edge definition and clarity while avoiding over-sharpening artifacts.",
                "fix_colors": "Fix colors in this image: correct white balance, adjust color temperature, and ensure natural skin tones if applicable."
            }
            
            edit_prompt = edit_prompts.get(edit_type, edit_instructions or "Enhance this image professionally.")
            
            # Initialize Gemini
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                state["error_message"] = "Image editing not available - GEMINI_API_KEY not set"
                return state
            
            # Configure Gemini API (matching media_agent pattern)
            genai.configure(api_key=gemini_api_key)
            gemini_model = 'gemini-2.5-flash-image-preview'
            
            # Create contents for Gemini
            contents = [
                {"text": edit_prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
            
            # Generate edited image using Gemini
            logger.info(f"Calling Gemini model: {gemini_model} for image editing")
            logger.info(f"Edit type: {edit_type}")
            logger.info(f"Image size: {len(image_data)} bytes")
            
            try:
                response = genai.GenerativeModel(gemini_model).generate_content(
                    contents=contents,
                )
                
                logger.info(f"Gemini response received: {len(response.candidates) if response.candidates else 0} candidates")
                
                # Extract image from response
                if not response.candidates or not response.candidates[0].content:
                    raise Exception("No image returned from Gemini - no candidates in response")
                
                edited_image_data = None
                candidate = response.candidates[0]
                
                # Check all parts for image data
                for i, part in enumerate(candidate.content.parts):
                    logger.info(f"Checking part {i}: inline_data={part.inline_data is not None if hasattr(part, 'inline_data') else False}")
                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                        # Gemini may return bytes or base64 string
                        image_data_raw = part.inline_data.data
                        if isinstance(image_data_raw, bytes):
                            edited_image_data = image_data_raw
                        else:
                            # If it's base64 string, decode it
                            edited_image_data = base64.b64decode(image_data_raw)
                        logger.info(f"Found image data in part {i}: {len(edited_image_data)} bytes")
                        break
                    elif hasattr(part, 'text') and part.text:
                        logger.warning(f"Part {i} contains text instead of image: {part.text[:200]}...")
                
                if not edited_image_data:
                    # Try to get text response for debugging
                    text_content = ""
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_content += part.text
                    logger.error(f"No image data found. Gemini text response: {text_content[:500]}...")
                    raise Exception(f"No image data in Gemini response. Response: {text_content[:200]}")
                    
            except Exception as gemini_error:
                error_str = str(gemini_error)
                logger.error(f"Gemini API error: {error_str}")
                
                # Check for specific error types
                if "API key" in error_str.lower() or "authentication" in error_str.lower():
                    state["error_message"] = "Gemini API authentication failed. Please check GEMINI_API_KEY."
                    return state
                elif "quota" in error_str.lower() or "limit" in error_str.lower():
                    state["error_message"] = "Gemini API quota exceeded. Please try again later."
                    return state
                else:
                    state["error_message"] = f"Failed to edit image with Gemini: {error_str}"
                    return state
            
            # Upload edited image to Supabase
            filename = f"custom_content_{user_id}_{platform}_{uuid.uuid4().hex[:8]}_edited.jpg"
            bucket_name = "user-uploads"
            
            storage_response = self.supabase.storage.from_(bucket_name).upload(
                filename,
                edited_image_data,
                file_options={"content-type": "image/jpeg"}
            )
            
            if hasattr(storage_response, 'error') and storage_response.error:
                raise Exception(f"Storage upload failed: {storage_response.error}")
            
            edited_image_url = self.supabase.storage.from_(bucket_name).get_public_url(filename)
            
            # Update state with edited image
            state["uploaded_media_url"] = edited_image_url
            state["edited_image_url"] = edited_image_url
            state["image_edit_type"] = edit_type
            
            logger.info(f"Successfully generated and uploaded edited image: {edited_image_url}")
            
            # Add success message
            message = {
                "role": "assistant",
                "content": f"✅ Image edited successfully! The {edit_type.replace('_', ' ')} has been applied.",
                "timestamp": datetime.now().isoformat(),
                "has_media": True,
                "media_url": edited_image_url,
                "media_type": "image"
            }
            state["conversation_messages"].append(message)
            
            return state
            
        except Exception as e:
            logger.error(f"Error generating edited image: {e}")
            state["error_message"] = f"Failed to edit image: {str(e)}"
            return state
    
    async def edit_image(self, state: CustomContentState) -> CustomContentState:
        """Offer AI image editing options for Image Post - simplified to two options"""
        try:
            state["current_step"] = ConversationStep.EDIT_IMAGE
            state["progress_percentage"] = 70
            
            # Check both uploaded and generated image URLs
            image_url = state.get("uploaded_media_url") or state.get("generated_media_url")
            if not image_url:
                # No image to edit, proceed to content generation
                state["current_step"] = ConversationStep.GENERATE_CONTENT
                return await self.generate_content(state)
            
            # Check if user wants to edit with Leo (has edit prompt)
            # This will be handled in process_user_input when user provides the edit description
            # Don't check here - let process_user_input handle it
            
            # Check if user already wants to edit (has been asked for description)
            if state.get("wants_to_edit_image"):
                # User has selected "Edit with Leo" and we're waiting for their description
                # Don't show the options again - just wait for their input
                logger.info("Waiting for user's edit description")
                return state
            
            # Check if we've already asked about editing
            last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
            edit_message_content = "Great! Your image is uploaded. Would you like to edit it with Leo before generating the caption?"
            
            if not last_message or edit_message_content not in last_message.get("content", ""):
                message = {
                    "role": "assistant",
                    "content": edit_message_content,
                    "timestamp": datetime.now().isoformat(),
                    "has_media": True,
                    "media_url": image_url,
                    "media_type": "image",
                    "options": [
                        {"value": "use_as_is", "label": "✅ Use as is"},
                        {"value": "edit_with_leo", "label": "✨ Edit with Leo"}
                    ]
                }
                state["conversation_messages"].append(message)
                logger.info("Offered simplified image editing options")
            else:
                logger.info("Image editing message already present")
            
            return state
            
        except Exception as e:
            logger.error(f"Error in edit_image: {e}")
            state["error_message"] = f"Failed to offer image editing: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
    
    async def _get_or_create_custom_content_campaign(self, user_id: str) -> str:
        """Get or create a default campaign for custom content"""
        try:
            # First, try to find an existing custom content campaign for this user
            response = self.supabase.table("content_campaigns").select("id").eq("user_id", user_id).eq("campaign_name", "Custom Content").execute()
            
            if response.data and len(response.data) > 0:
                # Campaign exists, return its ID
                return response.data[0]["id"]
            
            # Campaign doesn't exist, create it
            from datetime import datetime, timedelta
            today = datetime.now().date()
            week_end = today + timedelta(days=7)
            
            campaign_data = {
                "user_id": user_id,
                "campaign_name": "Custom Content",
                "week_start_date": today.isoformat(),
                "week_end_date": week_end.isoformat(),
                "status": "active",
                "total_posts": 0,
                "generated_posts": 0
            }
            
            result = self.supabase.table("content_campaigns").insert(campaign_data).execute()
            
            if result.data and len(result.data) > 0:
                campaign_id = result.data[0]["id"]
                logger.info(f"Created custom content campaign for user {user_id}: {campaign_id}")
                return campaign_id
            else:
                raise Exception("Failed to create custom content campaign")
                
        except Exception as e:
            logger.error(f"Error getting/creating custom content campaign: {e}")
            raise Exception(f"Failed to get or create custom content campaign: {str(e)}")
    
    async def display_result(self, state: CustomContentState) -> CustomContentState:
        """Display the final result to the user"""
        try:
            state["current_step"] = ConversationStep.DISPLAY_RESULT
            state["progress_percentage"] = 100
            
            final_post = state.get("final_post", {})
            platform = state.get("selected_platform", "")
            content_type = state.get("selected_content_type", "")
            
            message = {
                "role": "assistant",
                "content": f"🎉 Content creation complete! Your {content_type} for {platform} is ready and saved as a draft. You can now review, edit, or schedule it from your content dashboard. Is there anything else you'd like to create?",
                "timestamp": datetime.now().isoformat(),
                "final_post": final_post
            }
            state["conversation_messages"].append(message)
            
            logger.info("Content creation workflow completed successfully")
            
        except Exception as e:
            logger.error(f"Error in display_result: {e}")
            state["error_message"] = f"Failed to display result: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    async def handle_error(self, state: CustomContentState) -> CustomContentState:
        """Handle errors in the workflow"""
        try:
            state["current_step"] = ConversationStep.ERROR
            state["progress_percentage"] = 0
            
            error_message = state.get("error_message", "An unknown error occurred")
            
            message = {
                "role": "assistant",
                "content": f"I apologize, but I encountered an error: {error_message}. Let's start over or try a different approach. What would you like to do?",
                "timestamp": datetime.now().isoformat()
            }
            state["conversation_messages"].append(message)
            
            logger.error(f"Error handled: {error_message}")
            
        except Exception as e:
            logger.error(f"Error in handle_error: {e}")
            
        return state
    
    def _load_business_context(self, user_id: str) -> Dict[str, Any]:
        """Load business context from user profile"""
        try:
            # Get user profile from Supabase
            response = self.supabase.table("profiles").select("*").eq("id", user_id).execute()
            
            if response.data and len(response.data) > 0:
                profile_data = response.data[0]
                return self._extract_business_context(profile_data)
            else:
                logger.warning(f"No profile found for user {user_id}")
                return self._get_default_business_context()
                
        except Exception as e:
            logger.error(f"Error loading business context for user {user_id}: {e}")
            return self._get_default_business_context()

    def _get_default_business_context(self) -> Dict[str, Any]:
        """Get default business context when profile is not available"""
        return {
            "business_name": "Your Business",
            "industry": "General",
            "target_audience": "General audience",
            "brand_voice": "Professional and friendly",
            "content_goals": ["Engagement", "Awareness"],
            "brand_personality": "Approachable and trustworthy",
            "brand_values": ["Quality", "Trust"]
        }

    def _extract_business_context(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract business context from user profile"""
        return {
            "business_name": profile_data.get("business_name", ""),
            "industry": profile_data.get("industry", ""),
            "target_audience": profile_data.get("target_audience", ""),
            "brand_voice": profile_data.get("brand_voice", ""),
            "content_goals": profile_data.get("content_goals", []),
            "brand_personality": profile_data.get("brand_personality", ""),
            "brand_values": profile_data.get("brand_values", [])
        }

    async def _upload_base64_image_to_supabase(self, base64_data_url: str, user_id: str, platform: str) -> str:
        """Upload base64 image or video data to Supabase storage"""
        try:
            import base64
            import uuid
            
            # Parse the data URL
            if not base64_data_url.startswith("data:"):
                raise ValueError("Invalid base64 data URL format")
            
            # Extract content type and base64 data
            header, data = base64_data_url.split(",", 1)
            content_type = header.split(":")[1].split(";")[0]
            
            # Decode base64 data
            media_data = base64.b64decode(data)
            
            # Determine if it's a video or image
            is_video = content_type.startswith("video/")
            
            # Generate unique filename with proper extension
            if "/" in content_type:
                file_extension = content_type.split("/")[1]
                # Handle common video extensions
                if file_extension == "quicktime":
                    file_extension = "mov"
                elif file_extension == "x-msvideo":
                    file_extension = "avi"
            else:
                file_extension = "jpg" if not is_video else "mp4"
            
            filename = f"custom_content_{user_id}_{platform}_{uuid.uuid4().hex[:8]}.{file_extension}"
            file_path = filename  # Store directly in bucket root, not in subfolder
            
            # Use user-uploads bucket for user-uploaded content (both images and videos)
            bucket_name = "user-uploads"
            
            logger.info(f"Uploading {'video' if is_video else 'image'} to Supabase storage: {bucket_name}/{file_path}, content_type: {content_type}")
            
            # Upload to Supabase storage
            storage_response = self.supabase.storage.from_(bucket_name).upload(
                file_path,
                media_data,
                file_options={"content-type": content_type}
            )
            
            # Check for upload errors
            if hasattr(storage_response, 'error') and storage_response.error:
                raise Exception(f"Storage upload failed: {storage_response.error}")
            
            # Get public URL
            public_url = self.supabase.storage.from_(bucket_name).get_public_url(file_path)
            
            logger.info(f"Successfully uploaded {'video' if is_video else 'image'} to Supabase: {public_url}")
            return public_url
            
        except Exception as e:
            logger.error(f"Error uploading base64 media to Supabase: {e}")
            raise e
    
    async def _analyze_uploaded_image(self, image_url: str, user_description: str, business_context: Dict[str, Any]) -> str:
        """Analyze uploaded image using vision model"""
        try:
            import httpx
            import base64
            
            # Download image and convert to base64 to avoid timeout issues with Supabase URLs
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    image_response = await client.get(image_url)
                    image_response.raise_for_status()
                    image_data = image_response.content
                    
                    # Convert to base64
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    
                    # Determine image format from URL or content type
                    if image_url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        image_format = image_url.lower().split('.')[-1]
                        if image_format == 'jpg':
                            image_format = 'jpeg'
                    else:
                        # Try to detect from content type
                        content_type = image_response.headers.get('content-type', 'image/jpeg')
                        if 'png' in content_type:
                            image_format = 'png'
                        elif 'jpeg' in content_type or 'jpg' in content_type:
                            image_format = 'jpeg'
                        elif 'gif' in content_type:
                            image_format = 'gif'
                        elif 'webp' in content_type:
                            image_format = 'webp'
                        else:
                            image_format = 'jpeg'  # Default
                    
                    image_data_url = f"data:image/{image_format};base64,{base64_image}"
                    
            except Exception as download_error:
                error_str = str(download_error)
                # If it's a URL too long error, that's expected for large base64 data URLs
                if "URL too long" in error_str or "too long" in error_str.lower():
                    logger.debug(f"Base64 data URL too long, using direct URL for image analysis")
                else:
                    logger.warning(f"Failed to download image from {image_url}, trying direct URL: {download_error}")
                # Fallback: try direct URL (might work for public URLs)
                image_data_url = image_url
            
            # Create image analysis prompt
            analysis_prompt = f"""
            Analyze this image in detail for social media content creation. Focus on:
            
            1. Visual elements: What objects, people, settings, colors, and activities are visible?
            2. Mood and atmosphere: What feeling or vibe does the image convey?
            3. Brand relevance: How does this image relate to the business context?
            4. Content opportunities: What story or message could this image tell?
            5. Platform optimization: How would this work for different social media platforms?
            
            Business Context:
            - Business: {business_context.get('business_name', 'Not specified')}
            - Industry: {business_context.get('industry', 'Not specified')}
            - Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
            
            User Description: "{user_description}"
            
            Provide a detailed analysis that will help create engaging social media content.
            """
            
            # Analyze image using vision model with base64 data
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert visual content analyst specializing in social media marketing."},
                    {"role": "user", "content": [
                        {"type": "text", "text": analysis_prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}}
                    ]}
                ],
                temperature=0.3,
                max_tokens=500,
                timeout=60  # 60 second timeout
            )
            
            analysis = response.choices[0].message.content
            logger.info(f"Image analysis completed: {analysis[:100]}...")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing image: {e}")
            # Don't log as error if it's just a timeout - it's handled gracefully
            if "timeout" in str(e).lower() or "invalid_image_url" in str(e).lower() or "downloading" in str(e).lower():
                logger.warning(f"Image analysis timeout for {image_url}, continuing without analysis")
            return f"Image analysis failed: {str(e)}"

    def _create_content_prompt(self, description: str, platform: str, content_type: str, business_context: Dict[str, Any]) -> str:
        """Create a comprehensive prompt for content generation"""
        prompt = f"""
        Create a {content_type} for {platform} based on this description: "{description}"
        
        Business Context:
        - Business Name: {business_context.get('business_name', 'Not specified')}
        - Industry: {business_context.get('industry', 'Not specified')}
        - Target Audience: {business_context.get('target_audience', 'General audience')}
        - Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
        - Brand Personality: {business_context.get('brand_personality', 'Approachable and trustworthy')}
        
        Requirements:
        - Optimize for {platform} best practices
        - Match the brand voice and personality
        - Include relevant hashtags
        - Make it engaging and shareable
        - Keep it authentic to the business context
        
        Return the content in JSON format with these fields:
        - content: The main post content
        - title: A catchy title (if applicable)
        - hashtags: Array of relevant hashtags
        - call_to_action: Suggested call to action
        - engagement_hooks: Ways to encourage engagement
        """
        return prompt

    def _create_enhanced_content_prompt(self, description: str, platform: str, content_type: str, 
                                      business_context: Dict[str, Any], image_analysis: str, has_media: bool,
                                      clarification_1: str = "", clarification_2: str = "", clarification_3: str = "",
                                      generated_script: Optional[Dict[str, Any]] = None) -> str:
        """Create an enhanced prompt for content generation with image analysis and clarification answers"""
        # Build clarification section if any clarifications were provided
        clarification_section = ""
        if clarification_1 or clarification_2 or clarification_3:
            clarification_section = "\n\nAdditional Context from User:\n"
            if clarification_1:
                clarification_section += f"- Post Goal/Purpose: {clarification_1}\n"
            if clarification_2:
                clarification_section += f"- Target Audience: {clarification_2}\n"
            if clarification_3:
                clarification_section += f"- Tone/Style: {clarification_3}\n"
        
        # Add script information if available
        script_section = ""
        if generated_script:
            script_section = f"\n\nVIDEO SCRIPT (Use this as the foundation for your content):\n"
            script_section += f"Title: {generated_script.get('title', 'N/A')}\n"
            script_section += f"Hook: {generated_script.get('hook', 'N/A')}\n"
            script_section += f"Scenes: {json.dumps(generated_script.get('scenes', []), indent=2)}\n"
            script_section += f"Call to Action: {generated_script.get('call_to_action', 'N/A')}\n"
            script_section += f"Hashtags: {', '.join(generated_script.get('hashtags', []))}\n"
        
        base_prompt = f"""
        Create a {content_type} for {platform} based on this description: "{description}"
        {clarification_section}{script_section}
        
        Business Context:
        - Business Name: {business_context.get('business_name', 'Not specified')}
        - Industry: {business_context.get('industry', 'Not specified')}
        - Target Audience: {business_context.get('target_audience', 'General audience')}
        - Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
        - Brand Personality: {business_context.get('brand_personality', 'Approachable and trustworthy')}
        """
        
        # Determine content type category
        content_type_lower = content_type.lower()
        is_video = content_type_lower in ["reel", "shorts", "video"]
        is_image_carousel = content_type_lower in ["image post", "photo", "carousel"]
        is_text_post = content_type_lower == "text post"
        
        if is_video:
            # Video content generation rules
            enhanced_prompt = f"""
            {base_prompt}
            {f"\n\nIMAGE ANALYSIS:\n{image_analysis}" if has_media and image_analysis else ""}
            
            Requirements for Video Posts ({content_type}):
            - Create a caption optimized for {platform}
            - Include platform-specific hashtags (respect {platform} hashtag limits)
            - Add a compelling call-to-action (CTA)
            - For YouTube: Include a title optimized for SEO
            - Make it engaging and encourage viewers to watch
            - Reference the video script if provided
            
            CRITICAL INSTRUCTIONS:
            - Return ONLY a valid JSON object
            - Do NOT use markdown code blocks (no ```json or ```)
            - Use these exact field names:
            
            {{
              "content": "The video caption optimized for {platform}",
              "title": "{'Video title (required for YouTube)' if platform.lower() == 'youtube' else 'Optional title'}",
              "hashtags": ["array", "of", "platform", "specific", "hashtags"],
              "call_to_action": "Compelling CTA to encourage engagement"
            }}
            """
        elif is_image_carousel and has_media and image_analysis:
            # Image/Carousel content generation rules
            enhanced_prompt = f"""
            {base_prompt}
            
            IMAGE ANALYSIS:
            {image_analysis}
            
            Requirements for Images/Carousels ({content_type}):
            - Create captions that work across all images (if carousel)
            - Include platform-specific hashtags
            - Add alt text descriptions for accessibility
            - For carousels: Include per-slide descriptions
            - Make it engaging and shareable
            - Create a compelling narrative that connects images to your business
            
            CRITICAL INSTRUCTIONS:
            - Return ONLY a valid JSON object
            - Do NOT use markdown code blocks (no ```json or ```)
            - Use these exact field names:
            
            {{
              "content": "The main post caption",
              "title": "A catchy title",
              "hashtags": ["array", "of", "relevant", "hashtags"],
              "call_to_action": "Suggested call to action",
              "alt_text": "Accessibility alt text for the image(s)",
              "per_slide_descriptions": ["Description for slide 1", "Description for slide 2"] if content_type.lower() == "carousel" else null
            }}
            """
        elif is_text_post:
            # Text post generation rules
            enhanced_prompt = f"""
            {base_prompt}
            
            Requirements for Text Posts:
            - Generate 3 variations: Short, Medium, and Long versions
            - Include a compelling call-to-action (CTA)
            - Add relevant hashtags optimized for {platform}
            - Make it engaging and shareable
            - Optimize for {platform} character limits and best practices
            
            CRITICAL INSTRUCTIONS:
            - Return ONLY a valid JSON object
            - Do NOT use markdown code blocks (no ```json or ```)
            - Use these exact field names:
            
            {{
              "content": "The main post content (medium length version)",
              "content_short": "Short version (concise)",
              "content_long": "Long version (detailed)",
              "title": "A catchy title",
              "hashtags": ["array", "of", "relevant", "hashtags"],
              "call_to_action": "Compelling CTA"
            }}
            """
        elif has_media and image_analysis:
            # Default image content
            enhanced_prompt = f"""
            {base_prompt}
            
            IMAGE ANALYSIS:
            {image_analysis}
            
            Requirements:
            - Create content that perfectly complements and references the uploaded image
            - Use the image analysis to craft engaging, visual storytelling
            - Optimize for {platform} best practices with visual content
            - Match the brand voice and personality
            - Include relevant hashtags
            - Make it engaging and shareable
            
            CRITICAL INSTRUCTIONS:
            - Return ONLY a valid JSON object
            - Do NOT use markdown code blocks (no ```json or ```)
            - Use these exact field names:
            
            {{
              "content": "The main post content that references the image",
              "title": "A catchy title",
              "hashtags": ["array", "of", "relevant", "hashtags"],
              "call_to_action": "Suggested call to action"
            }}
            """
        else:
            # Default text-only content
            enhanced_prompt = f"""
            {base_prompt}
            
            Requirements:
            - Optimize for {platform} best practices
            - Match the brand voice and personality
            - Include relevant hashtags
            - Make it engaging and shareable
            - Keep it authentic to the business context
            
            CRITICAL INSTRUCTIONS:
            - Return ONLY a valid JSON object
            - Do NOT use markdown code blocks (no ```json or ```)
            - Use these exact field names:
            
            {{
              "content": "The main post content",
              "title": "A catchy title",
              "hashtags": ["array", "of", "relevant", "hashtags"],
              "call_to_action": "Suggested call to action"
            }}
            """
        
        return enhanced_prompt
    
    def _extract_hashtags(self, text: str) -> List[str]:
        """Extract hashtags from text"""
        import re
        hashtags = re.findall(r'#\w+', text)
        return hashtags[:10]  # Limit to 10 hashtags
    
    def _optimize_for_platform(self, content: Dict[str, Any], platform: str) -> Dict[str, Any]:
        """Apply platform-specific optimizations"""
        optimized = content.copy()
        
        # Platform-specific optimizations
        if platform == "Twitter/X":
            # Keep content concise
            if len(optimized.get("content", "")) > 280:
                optimized["content"] = optimized["content"][:277] + "..."
        elif platform == "Instagram":
            # Add more visual elements
            if not optimized.get("hashtags"):
                optimized["hashtags"] = ["#instagram", "#content", "#socialmedia"]
        elif platform == "LinkedIn":
            # Make it more professional
            if not optimized.get("call_to_action"):
                optimized["call_to_action"] = "What are your thoughts on this?"
        
        return optimized
    
    def _validate_script_structure(self, script_data: dict, user_description: str = "") -> dict:
        """Validate and normalize script structure to ensure all required fields exist"""
        if not isinstance(script_data, dict):
            logger.warning("Script data is not a dict, creating default structure")
            script_data = {}
        
        # Ensure required fields exist with defaults
        validated_script = {
            "title": str(script_data.get("title", f"Reel Script: {user_description[:50] if user_description else 'Untitled'}")),
            "hook": str(script_data.get("hook", user_description[:100] if user_description else "")),
            "scenes": [],
            "call_to_action": str(script_data.get("call_to_action", "")),
            "hashtags": [],
            "total_duration": str(script_data.get("total_duration", "30 seconds")),
            "tips": str(script_data.get("tips", ""))
        }
        
        # Validate and normalize scenes
        if isinstance(script_data.get("scenes"), list):
            for scene in script_data["scenes"]:
                if isinstance(scene, dict):
                    validated_scene = {
                        "duration": str(scene.get("duration", "")),
                        "visual": str(scene.get("visual", "")),
                        "audio": str(scene.get("audio", "")),
                        "on_screen_text": str(scene.get("on_screen_text", ""))
                    }
                    validated_script["scenes"].append(validated_scene)
        
        # Validate hashtags
        if isinstance(script_data.get("hashtags"), list):
            validated_script["hashtags"] = [str(tag) for tag in script_data["hashtags"] if tag]
        elif isinstance(script_data.get("hashtags"), str):
            # If hashtags is a string, try to parse it
            validated_script["hashtags"] = [tag.strip() for tag in script_data["hashtags"].split(",") if tag.strip()]
        
        # Preserve any additional fields
        for key, value in script_data.items():
            if key not in validated_script:
                # Only add if it's JSON serializable
                try:
                    json.dumps(value)
                    validated_script[key] = value
                except (TypeError, ValueError):
                    validated_script[key] = str(value)
        
        return validated_script
    
    async def process_user_input(self, state: CustomContentState, user_input: str, input_type: str = "text") -> CustomContentState:
        """Process user input and update state accordingly"""
        try:
            # Store user input in state
            state["user_input"] = user_input
            state["input_type"] = input_type
            
            current_step = state.get("current_step")
            
            # Handle ERROR state recovery
            if current_step == ConversationStep.ERROR:
                # Check if user wants to generate script
                user_input_lower = user_input.lower().strip()
                if any(phrase in user_input_lower for phrase in ["generate script", "generate scrpt", "create script", "script"]):
                    # Check if we have required info for script generation
                    platform = state.get("selected_platform")
                    content_type = state.get("selected_content_type")
                    user_desc = state.get("user_description")
                    
                    if platform and content_type and user_desc:
                        # Clear error and proceed to script generation
                        state["current_step"] = ConversationStep.GENERATE_SCRIPT
                        state["error_message"] = None
                        logger.info("Recovering from ERROR state - user wants to generate script")
                        return state
                    else:
                        # Missing required info - ask for it
                        missing = []
                        if not platform:
                            missing.append("platform")
                        if not content_type:
                            missing.append("content type")
                        if not user_desc:
                            missing.append("description")
                        
                        error_message = {
                            "role": "assistant",
                            "content": f"I need some information first. Please provide: {', '.join(missing)}. Let's start over - which platform would you like to create content for?",
                            "timestamp": datetime.now().isoformat()
                        }
                        state["conversation_messages"].append(error_message)
                        state["current_step"] = ConversationStep.ASK_PLATFORM
                        state["error_message"] = None
                        return state
                else:
                    # User wants to restart - clear error and go back to platform selection
                    state["current_step"] = ConversationStep.ASK_PLATFORM
                    state["error_message"] = None
                    logger.info("Recovering from ERROR state - restarting conversation")
                    return state
            
            # Process based on current step
            if current_step == ConversationStep.ASK_PLATFORM:
                # Parse platform selection
                platform = self._parse_platform_selection(user_input, state)
                if platform:
                    state["selected_platform"] = platform
                    state["retry_platform"] = False  # Clear retry flag on success
                    # Transition to next step
                    state["current_step"] = ConversationStep.ASK_CONTENT_TYPE
                else:
                    # Invalid input - stay on same step and show error with options
                    user_profile = state.get("user_profile", {})
                    connected_platforms = user_profile.get("social_media_platforms", [])
                    
                    # Format platform options same as greet_user
                    platform_options = []
                    for p in connected_platforms:
                        display_name = ' '.join(word.capitalize() for word in p.split('_'))
                        platform_options.append({"value": p, "label": display_name})
                    
                    error_message = {
                        "role": "assistant",
                        "content": f"I didn't recognize '{user_input}' as a valid platform. Please select one of the available platforms:",
                        "timestamp": datetime.now().isoformat(),
                        "platforms": connected_platforms,
                        "options": platform_options,
                        "is_error": True
                    }
                    state["conversation_messages"].append(error_message)
                    # Set retry flag so ask_platform knows to show options again
                    state["retry_platform"] = True
                    # Stay on the same step to re-prompt (graph will loop back)
                    state["current_step"] = ConversationStep.ASK_PLATFORM
                    logger.warning(f"Invalid platform selection: '{user_input}'. Available: {connected_platforms}")
                    
            elif current_step == ConversationStep.ASK_CONTENT_TYPE:
                # Parse content type selection
                content_type = self._parse_content_type_selection(user_input, state)
                if content_type:
                    state["selected_content_type"] = content_type
                    state["retry_content_type"] = False  # Clear retry flag on success
                    # Transition to next step
                    state["current_step"] = ConversationStep.ASK_DESCRIPTION
                else:
                    # Invalid input - stay on same step and show error with options
                    platform = state.get("selected_platform", "")
                    content_types = PLATFORM_CONTENT_TYPES.get(platform, [])
                    
                    error_message = {
                        "role": "assistant",
                        "content": f"I didn't recognize '{user_input}' as a valid content type for {platform}. Please select one of the available content types:",
                        "timestamp": datetime.now().isoformat(),
                        "content_types": content_types,
                        "options": [{"value": ct, "label": ct} for ct in content_types],
                        "is_error": True
                    }
                    state["conversation_messages"].append(error_message)
                    # Set retry flag so ask_content_type knows to show options again
                    state["retry_content_type"] = True
                    # Stay on the same step to re-prompt (graph will loop back)
                    state["current_step"] = ConversationStep.ASK_CONTENT_TYPE
                    logger.warning(f"Invalid content type selection: '{user_input}'. Available: {content_types}")
                    
            elif current_step == ConversationStep.ASK_DESCRIPTION:
                # Store user description
                state["user_description"] = user_input
                # Transition directly to media step (clarification questions removed)
                state["current_step"] = ConversationStep.ASK_MEDIA
                
            elif current_step == ConversationStep.APPROVE_CAROUSEL_IMAGES:
                # Carousel approval is handled in approve_carousel_images method
                # Don't modify state here - let execute_conversation_step handle it
                # This prevents adding extra steps
                pass
                
            elif current_step == ConversationStep.CONFIRM_CONTENT:
                # Handle content confirmation
                if user_input.lower().strip() in ["yes", "y", "save", "correct"]:
                    state["content_confirmed"] = True
                    state["current_step"] = ConversationStep.SELECT_SCHEDULE
                elif user_input.lower().strip() in ["no", "n", "change", "edit"]:
                    state["content_confirmed"] = False
                    state["current_step"] = ConversationStep.ASK_DESCRIPTION
                else:
                    state["error_message"] = "Please respond with 'yes' to save the content or 'no' to make changes."
                    
            elif current_step == ConversationStep.SELECT_SCHEDULE:
                # Handle schedule selection
                logger.info(f"Processing schedule selection with input: '{user_input}'")
                
                user_input_lower = user_input.lower().strip()
                # Handle "Post Now" button clicks (may include emoji)
                if user_input_lower in ["now", "immediately", "asap"] or "post now" in user_input_lower or "🚀" in user_input:
                    state["scheduled_for"] = datetime.now().isoformat()
                    logger.info(f"Set scheduled_for to now: {state['scheduled_for']}")
                else:
                    # Try to parse datetime from input
                    try:
                        # Try to import dateutil, fallback to datetime if not available
                        try:
                            from dateutil import parser
                            use_dateutil = True
                        except ImportError:
                            logger.warning("dateutil not available, using datetime fallback")
                            from datetime import datetime as dt
                            use_dateutil = False
                        
                        logger.info(f"Attempting to parse datetime: '{user_input}'")
                        
                        # Handle both ISO format (2025-09-28T10:37) and other formats
                        if 'T' in user_input and len(user_input.split('T')) == 2:
                            # ISO format from frontend
                            date_part, time_part = user_input.split('T')
                            if len(time_part) == 5:  # HH:MM format
                                time_part += ':00'  # Add seconds if missing
                            parsed_input = f"{date_part}T{time_part}"
                            logger.info(f"Formatted input: '{parsed_input}'")
                        else:
                            parsed_input = user_input
                        
                        if use_dateutil:
                            parsed_datetime = parser.parse(parsed_input)
                        else:
                            # Fallback to datetime parsing
                            parsed_datetime = dt.fromisoformat(parsed_input)
                        
                        # Ensure the datetime is timezone-aware
                        if parsed_datetime.tzinfo is None:
                            parsed_datetime = parsed_datetime.replace(tzinfo=None)
                        state["scheduled_for"] = parsed_datetime.isoformat()
                        logger.info(f"Successfully parsed datetime: {parsed_datetime.isoformat()}")
                    except Exception as e:
                        logger.error(f"Failed to parse datetime '{user_input}': {e}")
                        state["error_message"] = f"Please provide a valid date and time, or type 'now' to post immediately. Error: {str(e)}"
                        return state
                
                # Transition to save content
                state["current_step"] = ConversationStep.SAVE_CONTENT
                logger.info(f"Transitioning to SAVE_CONTENT with scheduled_for: {state.get('scheduled_for')}")
                logger.info(f"Current step after transition: {state.get('current_step')}")
                
                # Don't execute save_content directly - let the graph handle the transition
                # The graph will automatically call save_content based on the state transition
                
            elif current_step == ConversationStep.CONFIRM_MEDIA:
                # Handle media confirmation
                if user_input.lower().strip() in ["yes", "y", "correct", "proceed"]:
                    state["media_confirmed"] = True
                    # For Image Post, route to edit_image
                    # For other types, go to generate_content
                    content_type = state.get("selected_content_type", "").lower()
                    if content_type in ["image post", "image", "photo"]:
                        # Route to edit_image step for Image Post
                        state["current_step"] = ConversationStep.EDIT_IMAGE
                        logger.info("Media confirmed for Image Post, routing to EDIT_IMAGE")
                    else:
                        state["current_step"] = ConversationStep.GENERATE_CONTENT
                elif user_input.lower().strip() in ["no", "n", "incorrect", "wrong"]:
                    state["media_confirmed"] = False
                    # Clear previous media
                    state.pop("uploaded_media_url", None)
                    state.pop("uploaded_media_filename", None)
                    state.pop("uploaded_media_size", None)
                    state.pop("uploaded_media_type", None)
                    state["current_step"] = ConversationStep.ASK_MEDIA
                else:
                    state["error_message"] = "Please respond with 'yes' to proceed or 'no' to upload a different file."
                    
            elif current_step == ConversationStep.EDIT_IMAGE:
                # Handle image editing choice
                user_input_lower = user_input.lower().strip()
                
                if user_input_lower in ["use_as_is", "use as is", "skip", "no", "n"]:
                    # User wants to use image as is
                    state["use_image_as_is"] = True
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info("User chose to use image as is")
                elif user_input_lower in ["edit_with_leo", "edit with leo", "edit", "leo"] or "edit with leo" in user_input_lower:
                    # User wants to edit with Leo - ask for edit description
                    state["wants_to_edit_image"] = True
                    # Clear any previous edit prompt
                    state.pop("image_edit_prompt", None)
                    # Ask user to describe what they want to edit
                    message = {
                        "role": "assistant",
                        "content": "Great! Describe what you'd like me to edit in your image. For example: 'Make it brighter', 'Change background to blue', 'Remove the person on the left', etc.",
                        "timestamp": datetime.now().isoformat()
                    }
                    state["conversation_messages"].append(message)
                    logger.info("Asked user for edit description")
                elif state.get("wants_to_edit_image"):
                    # User provided edit description - apply the edit
                    edit_prompt = user_input.strip()
                    if not edit_prompt:
                        state["error_message"] = "Please describe what you'd like to edit in the image."
                        return state
                    
                    # Apply natural language edit to image
                    result = await self.generate_edited_image_with_prompt(state, edit_prompt)
                    if result.get("error_message"):
                        # Error occurred, stay in edit_image
                        return result
                    
                    # Success - clear the flag and proceed to generate content with edited image
                    state["wants_to_edit_image"] = False
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info(f"Image edited with prompt: {edit_prompt}, proceeding to generate content")
                    return await self.generate_content(state)
                else:
                    state["error_message"] = "Please select 'Use as is' or 'Edit with Leo'."
                    
            elif current_step == ConversationStep.ASK_MEDIA:
                # Check if this is a carousel post - if so, handle carousel image source selection
                content_type = state.get("selected_content_type", "")
                if content_type and content_type.lower() == "carousel":
                    # Carousel handling is done in ask_media() method itself
                    # It transitions to ASK_CAROUSEL_IMAGE_SOURCE
                    result = await self.ask_media(state)
                    return result
                
                # Parse media choice for regular posts
                media_choice = self._parse_media_choice(user_input)
                logger.info(f"Media choice parsed: '{media_choice}' from input: '{user_input}'")
                
                if media_choice == "upload_image":
                    state["has_media"] = True
                    state["media_type"] = MediaType.IMAGE
                    state["should_generate_media"] = False
                    state["current_step"] = ConversationStep.HANDLE_MEDIA
                    logger.info("Set to HANDLE_MEDIA for upload_image")
                elif media_choice == "upload_video":
                    state["has_media"] = True
                    state["media_type"] = MediaType.VIDEO
                    state["should_generate_media"] = False
                    state["current_step"] = ConversationStep.HANDLE_MEDIA
                    logger.info("Set to HANDLE_MEDIA for upload_video")
                elif media_choice == "generate_image":
                    state["has_media"] = True
                    state["media_type"] = MediaType.IMAGE
                    state["should_generate_media"] = True
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info("Set to GENERATE_CONTENT for generate_image - will generate immediately")
                    # Don't return here - let execute_conversation_step handle it automatically
                elif media_choice == "generate_video":
                    state["has_media"] = True
                    state["media_type"] = MediaType.VIDEO
                    state["should_generate_media"] = True
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info("Set to GENERATE_CONTENT for generate_video")
                elif media_choice == "generate_script":
                    state["has_media"] = True
                    state["media_type"] = MediaType.VIDEO
                    state["should_generate_media"] = False
                    state["current_step"] = ConversationStep.GENERATE_SCRIPT
                    logger.info("Set to GENERATE_SCRIPT for generate_script")
                else:  # skip_media
                    state["has_media"] = False
                    state["media_type"] = MediaType.NONE
                    state["should_generate_media"] = False
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info("Set to GENERATE_CONTENT for skip_media")
                    
            elif current_step == ConversationStep.PREVIEW_AND_EDIT:
                # Handle preview and edit actions
                user_input_lower = user_input.lower().strip()
                
                # Determine if this is an Image Post
                content_type = state.get("selected_content_type", "").lower()
                is_image_post = content_type in ["image post", "image", "photo"]
                image_edit_commands = ["enhance", "remove_background", "change_background", "fix_colors", 
                                      "sharpen", "cleanup", "add_filter", "crop", "revisualize"]
                
                # FIRST: Check if user wants to proceed to schedule (highest priority)
                proceed_commands = ["proceed", "looks good", "continue", "yes", "y", "ok", "okay", "post", "post this", "schedule", "publish", "ready", "done", "save", "finalize"]
                if any(cmd in user_input_lower for cmd in proceed_commands) or user_input_lower in proceed_commands:
                    # User wants to proceed to schedule
                    state["preview_confirmed"] = True
                    # Clear any edit flags
                    state["wants_to_edit"] = False
                    state.pop("edit_prompt", None)
                    # Don't change current_step here - let the graph handle the transition
                    logger.info("User confirmed preview, will transition to SELECT_SCHEDULE")
                elif user_input_lower.startswith("switch_version:") or "switch to version" in user_input_lower:
                    # User wants to switch to a specific version
                    content_history = state.get("content_history", [])
                    if not content_history:
                        logger.warning("No content history available")
                    else:
                        # Extract version number
                        version_num = None
                        if user_input_lower.startswith("switch_version:"):
                            try:
                                version_num = int(user_input_lower.split("switch_version:")[1].strip())
                            except (ValueError, IndexError):
                                logger.warning(f"Invalid version number in input: {user_input}")
                        elif "switch to version" in user_input_lower:
                            try:
                                parts = user_input_lower.split("switch to version")
                                version_num = int(parts[1].strip()) if len(parts) > 1 else None
                            except (ValueError, IndexError):
                                logger.warning(f"Invalid version number in input: {user_input}")
                        
                        if version_num:
                            # Find version in history (version numbers are 1-indexed)
                            version_index = None
                            for idx, version in enumerate(content_history):
                                if version.get("version") == version_num:
                                    version_index = idx
                                    break
                            
                            if version_index is not None:
                                # Switch to this version
                                selected_version = content_history[version_index]
                                state["current_content_version"] = version_index
                                state["generated_content"] = selected_version["content"].copy()
                                
                                # Update is_current flags
                                for i, version in enumerate(content_history):
                                    version["is_current"] = (i == version_index)
                                
                                # Mark that version was switched - this will refresh preview
                                state["version_switched"] = True
                                state["preview_confirmed"] = False  # Reset preview confirmation
                                
                                logger.info(f"Switched to version {version_num} (index {version_index})")
                            else:
                                logger.warning(f"Version {version_num} not found in history")
                        else:
                            logger.warning("Could not extract version number from input")
                # SECOND: Check if this is an image editing command (for Image Post)
                elif user_input_lower in image_edit_commands and is_image_post:
                    # User wants to edit the image
                    edit_type = user_input_lower
                    state["wants_to_edit_image"] = True
                    state["image_edit_type"] = edit_type
                    # Generate edited image
                    result = await self.generate_edited_image(state, edit_type)
                    if result.get("error_message"):
                        # Error occurred, stay in preview
                        return result
                    # Success - regenerate content with edited image
                    state["current_step"] = ConversationStep.GENERATE_CONTENT
                    logger.info(f"Image edited with type: {edit_type}, regenerating content")
                elif user_input_lower in ["edit", "change", "modify"]:
                    # User wants to edit - this will be handled by showing edit input in frontend
                    state["wants_to_edit"] = True
                    # Don't change step - stay in preview to show edit input
                else:
                    # Assume it's an edit prompt (natural language)
                    state["wants_to_edit"] = True
                    state["edit_prompt"] = user_input
                    # Store the edit prompt for apply_content_edit
                    logger.info(f"Received edit prompt: {user_input}")
                    
            elif current_step == ConversationStep.ASK_ANOTHER_CONTENT:
                # Handle another content choice
                user_input_lower = user_input.lower().strip()
                if user_input_lower in ["yes", "y", "create", "another", "generate", "create another post"]:
                    # Reset state for new content generation
                    state["current_step"] = ConversationStep.ASK_PLATFORM
                    state["progress_percentage"] = 0
                    # Clear previous content data
                    state.pop("selected_platform", None)
                    state.pop("selected_content_type", None)
                    state.pop("user_description", None)
                    state.pop("has_media", None)
                    state.pop("media_type", None)
                    state.pop("uploaded_media_url", None)
                    state.pop("uploaded_media_filename", None)
                    state.pop("uploaded_media_size", None)
                    state.pop("uploaded_media_type", None)
                    state.pop("should_generate_media", None)
                    state.pop("generated_content", None)
                    state.pop("final_post", None)
                    state.pop("scheduled_for", None)
                    state.pop("content_confirmed", None)
                    state.pop("media_confirmed", None)
                    state.pop("preview_confirmed", None)
                    state.pop("is_complete", None)
                    state.pop("content_history", None)
                    state.pop("current_content_version", None)
                    state.pop("wants_to_edit", None)
                    state.pop("edit_prompt", None)
                    state.pop("edited_image_url", None)
                    state.pop("image_edit_type", None)
                    state.pop("use_image_as_is", None)
                    state.pop("wants_to_edit_image", None)
                    logger.info("User wants to create another post - resetting state")
                elif user_input_lower in ["no", "n", "done", "exit", "finish", "i'm done for now", "done for now"]:
                    # Mark as complete to exit - flow breaks here
                    state["is_complete"] = True
                    logger.info("User is done - marking conversation as complete")
                else:
                    state["error_message"] = "Please respond with 'yes' to create another content or 'no' to finish."
            
            logger.info(f"Processed user input for step: {current_step}")
            
        except Exception as e:
            logger.error(f"Error processing user input: {e}")
            state["error_message"] = f"Failed to process input: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    def _parse_platform_selection(self, user_input: str, state: CustomContentState) -> Optional[str]:
        """Parse platform selection from user input with improved matching"""
        user_profile = state.get("user_profile", {})
        connected_platforms = user_profile.get("social_media_platforms", [])
        
        if not connected_platforms:
            return None
        
        user_input_clean = user_input.strip()
        user_input_lower = user_input_clean.lower()
        
        # Try to match by number first (for backward compatibility)
        try:
            index = int(user_input_clean) - 1
            if 0 <= index < len(connected_platforms):
                return connected_platforms[index]
        except ValueError:
            pass
        
        # Try to match by exact name (for button clicks)
        for platform in connected_platforms:
            if platform == user_input_clean:
                return platform
        
        # Try to match by exact lowercase name
        for platform in connected_platforms:
            if platform.lower() == user_input_lower:
                return platform
        
        # Try to match by partial name (for text input)
        for platform in connected_platforms:
            platform_lower = platform.lower()
            # Check if platform name is contained in user input or vice versa
            if platform_lower in user_input_lower or user_input_lower in platform_lower:
                return platform
        
        # Try fuzzy matching with common platform name variations
        platform_variations = {
            "facebook": ["fb", "facebook"],
            "instagram": ["ig", "insta", "instagram"],
            "linkedin": ["linkedin", "linked in"],
            "twitter": ["twitter", "x", "twitter/x"],
            "youtube": ["yt", "youtube", "you tube"],
            "tiktok": ["tiktok", "tik tok", "tt"],
            "pinterest": ["pinterest", "pin"],
            "whatsapp": ["whatsapp", "whats app", "wa", "whatsapp business"]
        }
        
        # Check if user input matches any variation
        for platform in connected_platforms:
            platform_lower = platform.lower()
            variations = platform_variations.get(platform_lower, [platform_lower])
            for variation in variations:
                if variation in user_input_lower or user_input_lower in variation:
                    return platform
        
        return None
    
    def _parse_content_type_selection(self, user_input: str, state: CustomContentState) -> Optional[str]:
        """Parse content type selection from user input with improved matching"""
        platform = state.get("selected_platform", "")
        content_types = PLATFORM_CONTENT_TYPES.get(platform, [])
        
        if not content_types:
            return None
        
        user_input_clean = user_input.strip()
        user_input_lower = user_input_clean.lower()
        
        # Try to match by number first (for backward compatibility)
        try:
            index = int(user_input_clean) - 1
            if 0 <= index < len(content_types):
                return content_types[index]
        except ValueError:
            pass
        
        # Try to match by exact name (for button clicks)
        for content_type in content_types:
            if content_type == user_input_clean:
                return content_type
        
        # Try to match by exact lowercase name
        for content_type in content_types:
            if content_type.lower() == user_input_lower:
                return content_type
        
        # Try to match by partial name (for text input)
        for content_type in content_types:
            content_type_lower = content_type.lower()
            # Check if content type name is contained in user input or vice versa
            if content_type_lower in user_input_lower or user_input_lower in content_type_lower:
                return content_type
        
        # Try fuzzy matching with common content type variations
        content_type_variations = {
            "text post": ["text", "post", "text post"],
            "photo": ["photo", "image", "picture", "pic"],
            "video": ["video", "vid", "movie", "clip"],
            "carousel": ["carousel", "slideshow", "multiple images"],
            "story": ["story", "stories"],
            "reel": ["reel", "reels"],
            "tweet": ["tweet", "post"],
            "thread": ["thread", "threads"],
            "article": ["article", "blog", "blog post"],
            "live": ["live", "live stream", "live broadcast"],
            "poll": ["poll", "polling", "survey"],
            "question": ["question", "q&a", "qa"]
        }
        
        # Check if user input matches any variation
        for content_type in content_types:
            content_type_lower = content_type.lower()
            variations = content_type_variations.get(content_type_lower, [content_type_lower])
            for variation in variations:
                if variation in user_input_lower or user_input_lower in variation:
                    return content_type
        
        return None
    
    def _parse_media_choice(self, user_input: str) -> str:
        """Parse media choice from user input"""
        user_input_lower = user_input.lower().strip()
        
        # Handle direct button values (for backward compatibility)
        if user_input_lower in ["upload_image", "upload_video", "generate_image", "generate_video", "generate_script", "skip_media"]:
            return user_input_lower
        
        # Handle button labels from frontend
        if "upload an image" in user_input_lower or "📷" in user_input:
            return "upload_image"
        elif "upload a video" in user_input_lower or "🎥" in user_input:
            return "upload_video"
        elif "generate an image" in user_input_lower or ("🎨" in user_input and "script" not in user_input_lower):
            return "generate_image"
        elif "generate a video" in user_input_lower or "🎬" in user_input:
            return "generate_video"
        elif "generate a script" in user_input_lower or "generate script" in user_input_lower or ("📝" in user_input and "script" in user_input_lower):
            return "generate_script"
        elif "skip media" in user_input_lower or "text-only" in user_input_lower or ("📝" in user_input and "script" not in user_input_lower):
            return "skip_media"
        
        # Handle text-based parsing (for manual input)
        if any(word in user_input_lower for word in ["upload", "image", "photo", "picture"]):
            return "upload_image"
        elif any(word in user_input_lower for word in ["upload", "video", "movie", "clip"]):
            return "upload_video"
        elif any(word in user_input_lower for word in ["generate", "create", "image", "photo"]) and "script" not in user_input_lower:
            return "generate_image"
        elif any(word in user_input_lower for word in ["generate", "create", "video", "movie"]) and "script" not in user_input_lower:
            return "generate_video"
        elif any(word in user_input_lower for word in ["generate", "create", "script"]):
            return "generate_script"
        elif any(word in user_input_lower for word in ["skip", "none", "no", "text only"]):
            return "skip_media"
        else:
            return "skip_media"
    
    async def upload_media(self, state: CustomContentState, media_file: bytes, filename: str, content_type: str) -> CustomContentState:
        """Upload media file directly to Supabase storage (for videos) or store as base64 (for small images)"""
        try:
            user_id = state["user_id"]
            platform = state.get("selected_platform", "general")
            
            # Validate inputs
            if not media_file:
                raise Exception("No file content provided")
            if not filename:
                raise Exception("No filename provided")
            if not content_type:
                raise Exception("No content type provided")
            
            is_video = content_type.startswith("video/")
            file_size = len(media_file)
            
            logger.info(f"Uploading media: {filename}, size: {file_size} bytes, type: {content_type}, is_video: {is_video}")
            
            # For videos or large files, upload directly to Supabase storage
            # For small images, we can store as base64 for faster processing
            if is_video or file_size > 5 * 1024 * 1024:  # 5MB threshold
                # Upload directly to Supabase storage
                file_extension = filename.split('.')[-1] if '.' in filename else ('mp4' if is_video else 'jpg')
                # Handle common video extensions
                if file_extension.lower() == 'quicktime':
                    file_extension = 'mov'
                elif file_extension.lower() == 'x-msvideo':
                    file_extension = 'avi'
                
                unique_filename = f"custom_content_{user_id}_{platform}_{uuid.uuid4().hex[:8]}.{file_extension}"
                bucket_name = "user-uploads"
                
                logger.info(f"Uploading {'video' if is_video else 'large file'} directly to Supabase: {bucket_name}/{unique_filename}")
                
                # Upload to Supabase storage
                storage_response = self.supabase.storage.from_(bucket_name).upload(
                    unique_filename,
                    media_file,
                    file_options={"content-type": content_type}
                )
                
                # Check for upload errors
                if hasattr(storage_response, 'error') and storage_response.error:
                    raise Exception(f"Storage upload failed: {storage_response.error}")
            
                # Get public URL
                public_url = self.supabase.storage.from_(bucket_name).get_public_url(unique_filename)
                
                logger.info(f"Successfully uploaded {'video' if is_video else 'file'} to Supabase: {public_url}")
                
                # Store the public URL in state (not base64)
                state["uploaded_media_url"] = public_url
                state["uploaded_media_filename"] = unique_filename
                state["uploaded_media_size"] = file_size
                state["uploaded_media_type"] = content_type
            else:
                # For small images, store as base64 for faster processing
                logger.info(f"Storing small image as base64: {filename}")
                file_extension = filename.split('.')[-1] if '.' in filename else 'jpg'
                unique_filename = f"custom_content_{user_id}_{platform}_{uuid.uuid4()}.{file_extension}"
                
                # Store media in session state (base64 encoded)
                media_base64 = base64.b64encode(media_file).decode('utf-8')
                
                # Store in state
                state["uploaded_media_url"] = f"data:{content_type};base64,{media_base64}"
                state["uploaded_media_filename"] = unique_filename
                state["uploaded_media_size"] = file_size
                state["uploaded_media_type"] = content_type
            
            # Transition to media confirmation
            state["current_step"] = ConversationStep.CONFIRM_MEDIA
            state["progress_percentage"] = 60
            
            logger.info(f"Media processed for user {user_id}: {unique_filename}")
            
        except Exception as e:
            logger.error(f"Error uploading media: {e}")
            state["error_message"] = f"Failed to upload media: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            
        return state
    
    def get_conversation_state(self, conversation_id: str) -> Optional[CustomContentState]:
        """Get conversation state by ID (for persistence)"""
        # This would typically load from a database
        # For now, we'll return None as state is managed in memory
        return None
    
    def save_conversation_state(self, state: CustomContentState) -> bool:
        """Save conversation state (for persistence)"""
        try:
            # This would typically save to a database
            # For now, we'll just log it
            logger.info(f"Conversation state saved: {state['conversation_id']}")
            return True
        except Exception as e:
            logger.error(f"Error saving conversation state: {e}")
            return False
    
    def _should_proceed_from_platform(self, state: CustomContentState) -> str:
        """Determine if we should proceed from platform selection or retry"""
        # Check if platform is selected - if yes, proceed
        if state.get("selected_platform"):
            return "continue"
        # If retry flag is set, loop back to ask again
        if state.get("retry_platform", False):
            return "retry"
        # If no platform selected and not a retry, this is first time - proceed to ask
        # (The ask_platform node will handle showing the options)
        return "continue"
    
    def _should_proceed_from_content_type(self, state: CustomContentState) -> str:
        """Determine if we should proceed from content type selection or retry"""
        # Check if content type is selected - if yes, proceed
        if state.get("selected_content_type"):
            return "continue"
        # If retry flag is set, loop back to ask again
        if state.get("retry_content_type", False):
            return "retry"
        # If no content type selected and not a retry, this is first time - proceed to ask
        # (The ask_content_type node will handle showing the options)
        return "continue"
    
    def _should_handle_media(self, state: CustomContentState) -> str:
        """Determine if media should be handled, generated, or skipped"""
        current_step = state.get("current_step")
        
        # If we're generating a script, route to generate_script
        if current_step == ConversationStep.GENERATE_SCRIPT:
            return "generate_script"
        
        # If Text Post, skip media and go directly to content generation
        content_type = state.get("selected_content_type", "")
        if content_type and content_type.lower() == "text post":
            return "skip"
        
        if state.get("has_media", False):
            if state.get("should_generate_media", False):
                return "generate"
            else:
                return "handle"
        return "skip"
    
    def _should_proceed_after_script(self, state: CustomContentState) -> str:
        """Determine next step after script generation"""
        # If current_step is CONFIRM_SCRIPT, the execute_conversation_step will handle it
        # and return state without proceeding to generate_content
        if state.get("current_step") == ConversationStep.CONFIRM_SCRIPT:
            return "confirm"  # Stop and show script
        return "proceed"  # Continue to content generation (shouldn't happen normally)
    
    def _should_proceed_after_media(self, state: CustomContentState) -> str:
        """Determine next step after media confirmation"""
        if state.get("current_step") == ConversationStep.ERROR:
            return "error"
        
        # Check if user wants to edit image (for Image Post)
        if state.get("wants_to_edit_image", False):
            state["wants_to_edit_image"] = False  # Reset flag
            return "edit_image"
        
        # Check if user confirmed media
        if state.get("media_confirmed", False):
            # For Image Post, check if we should offer editing
            content_type = state.get("selected_content_type", "").lower()
            media_type = state.get("media_type", "")
            if content_type in ["image post", "image", "photo"] and str(media_type).lower() == "image":
                # Check if user selected "use as is" or wants to edit
                if state.get("use_image_as_is", False):
                    return "proceed"
                # Default: offer editing for Image Post
                return "edit_image"
            return "proceed"
        elif state.get("validation_errors"):
            return "retry"
        else:
            return "proceed"  # Default to proceed if no explicit confirmation
    
    def _should_proceed_after_preview(self, state: CustomContentState) -> str:
        """Determine next step after preview and edit"""
        if state.get("current_step") == ConversationStep.ERROR:
            return "error"
        
        # Check if user wants to proceed to schedule
        if state.get("preview_confirmed", False):
            return "proceed"
        
        # Check if user wants to edit (will be set in process_user_input)
        if state.get("wants_to_edit", False):
            return "edit"  # Stay in preview mode to show edit input or apply edit
        
        # Default: stay in preview (waiting for user action)
        return "edit"  # This will loop back to preview_and_edit
    
    def get_user_platforms(self, user_id: str) -> List[str]:
        """Get user's connected platforms from their profile"""
        try:
            profile_response = self.supabase.table("profiles").select("social_media_platforms").eq("id", user_id).execute()
            
            if profile_response.data and profile_response.data[0]:
                platforms = profile_response.data[0].get("social_media_platforms", [])
                return platforms if platforms else []
            
            return []
        except Exception as e:
            logger.error(f"Error getting user platforms: {e}")
            return []
    
    async def _load_user_profile(self, user_id: str) -> dict:
        """Load user profile from Supabase"""
        try:
            profile_response = self.supabase.table("profiles").select("*").eq("id", user_id).execute()
            
            if profile_response.data and profile_response.data[0]:
                return profile_response.data[0]
            
            return {}
        except Exception as e:
            logger.error(f"Error loading user profile: {e}")
            return {}
    
    async def execute_conversation_step(self, state: CustomContentState, user_input: str = None) -> CustomContentState:
        """Execute the next step in the conversation using LangGraph"""
        try:
            # Process user input if provided
            if user_input:
                logger.info(f"Processing user input: '{user_input}'")
                state = await self.process_user_input(state, user_input, "text")
                logger.info(f"After processing input, current_step: {state.get('current_step')}")
                
                # If process_user_input set current_step to GENERATE_CONTENT (for image generation),
                # automatically continue to execute it without waiting for another user input
                if state.get("current_step") == ConversationStep.GENERATE_CONTENT and state.get("should_generate_media", False):
                    logger.info("Image generation triggered - automatically executing generate_content")
                    # Continue to execute the GENERATE_CONTENT step below
            
            # If there's an error, try to recover if user provided meaningful input
            if state.get("current_step") == ConversationStep.ERROR:
                # Check if user wants to generate script or continue
                if user_input:
                    user_input_lower = user_input.lower().strip()
                    # Check if user wants to generate script
                    if any(phrase in user_input_lower for phrase in ["generate script", "generate scrpt", "create script", "script"]):
                        # Check if we have required info for script generation
                        platform = state.get("selected_platform")
                        content_type = state.get("selected_content_type")
                        user_description = state.get("user_description")
                        
                        if platform and content_type and user_description:
                            # Clear error and proceed to script generation
                            state["current_step"] = ConversationStep.GENERATE_SCRIPT
                            state["error_message"] = None
                            logger.info("Recovering from ERROR state - proceeding to generate script")
                        else:
                            # Missing required info - ask for it
                            missing = []
                            if not platform:
                                missing.append("platform")
                            if not content_type:
                                missing.append("content type")
                            if not user_description:
                                missing.append("description")
                            
                            error_message = {
                                "role": "assistant",
                                "content": f"I need some information first. Please provide: {', '.join(missing)}. Let's start over - which platform would you like to create content for?",
                                "timestamp": datetime.now().isoformat()
                            }
                            state["conversation_messages"].append(error_message)
                            state["current_step"] = ConversationStep.ASK_PLATFORM
                            state["error_message"] = None
                            return state
                    else:
                        # User wants to restart or continue - clear error and go back to platform selection
                        state["current_step"] = ConversationStep.ASK_PLATFORM
                        state["error_message"] = None
                        logger.info("Recovering from ERROR state - restarting conversation")
                        return await self.ask_platform(state)
                else:
                    # No user input, just show error message
                    return state
            
            # Execute the current step based on the current_step in state
            current_step = state.get("current_step")
            logger.info(f"Executing conversation step: {current_step}")
            
            if current_step == ConversationStep.GREET:
                result = await self.greet_user(state)
            elif current_step == ConversationStep.ASK_PLATFORM:
                result = await self.ask_platform(state)
            elif current_step == ConversationStep.ASK_CONTENT_TYPE:
                result = await self.ask_content_type(state)
            elif current_step == ConversationStep.ASK_DESCRIPTION:
                result = await self.ask_description(state)
            elif current_step == ConversationStep.PREVIEW_AND_EDIT:
                # Check if preview is confirmed - if so, transition to select_schedule
                if state.get("preview_confirmed", False):
                    logger.info("Preview confirmed, transitioning to SELECT_SCHEDULE")
                    state["current_step"] = ConversationStep.SELECT_SCHEDULE
                    result = await self.select_schedule(state)
                else:
                    result = await self.preview_and_edit(state)
            elif current_step == ConversationStep.ASK_MEDIA:
                result = await self.ask_media(state)
            elif current_step == ConversationStep.GENERATE_SCRIPT:
                result = await self.generate_script(state)
            elif current_step == ConversationStep.CONFIRM_SCRIPT:
                # Script is already generated and displayed, just return state
                # User can save or regenerate from frontend
                result = state
                logger.info("Script is displayed, waiting for user to save or regenerate")
            elif current_step == ConversationStep.ASK_CAROUSEL_IMAGE_SOURCE:
                result = await self.ask_carousel_image_source(state, user_input)
            elif current_step == ConversationStep.GENERATE_CAROUSEL_IMAGE:
                result = await self.generate_carousel_image(state, user_input)
            elif current_step == ConversationStep.APPROVE_CAROUSEL_IMAGES:
                result = await self.approve_carousel_images(state, user_input)
            elif current_step == ConversationStep.HANDLE_CAROUSEL_UPLOAD:
                result = await self.handle_carousel_upload(state)
            elif current_step == ConversationStep.CONFIRM_CAROUSEL_UPLOAD_DONE:
                result = await self.confirm_carousel_upload_done(state, user_input)
            elif current_step == ConversationStep.HANDLE_MEDIA:
                result = await self.handle_media(state)
            elif current_step == ConversationStep.VALIDATE_MEDIA:
                result = await self.validate_media(state)
            elif current_step == ConversationStep.CONFIRM_MEDIA:
                result = await self.confirm_media(state)
            elif current_step == ConversationStep.GENERATE_CONTENT:
                try:
                    result = await self.generate_content(state)
                    # generate_content calls preview_and_edit internally, but if it didn't transition,
                    # ensure we continue to preview_and_edit
                    # After generate_content, if it transitioned to PREVIEW_AND_EDIT, automatically continue
                    # This ensures preview is shown without waiting for another user input
                    if result.get("current_step") == ConversationStep.PREVIEW_AND_EDIT:
                        logger.info("Content generated, checking if preview message exists")
                        # Check if preview message is already in conversation_messages
                        has_preview_message = any(msg.get("preview_mode") for msg in result.get("conversation_messages", []))
                        if has_preview_message:
                            logger.info("Preview message already exists, preview should be displayed")
                        else:
                            logger.info("Preview message not found, calling preview_and_edit to add it")
                            result = await self.preview_and_edit(result)
                except Exception as e:
                    logger.error(f"Error in generate_content step: {e}")
                    # Don't set to ERROR - continue with content generation without images
                    # The generate_content function should handle errors internally
                    # If it still fails, create a basic content message
                    state["current_step"] = ConversationStep.CONFIRM_CONTENT
                    state["progress_percentage"] = 85
                    # Create a basic error message but continue
                    error_message = {
                        "role": "assistant",
                        "content": f"I encountered an issue analyzing the images, but I've generated content based on your description. Please review it below.",
                        "timestamp": datetime.now().isoformat()
                    }
                    state["conversation_messages"].append(error_message)
                    result = await self.confirm_content(state)
            elif current_step == ConversationStep.CONFIRM_CONTENT:
                result = await self.confirm_content(state)
            elif current_step == ConversationStep.SELECT_SCHEDULE:
                # Check if user has already selected a schedule (scheduled_for is set)
                if state.get("scheduled_for"):
                    # User has already selected schedule, transition to save_content
                    logger.info(f"Schedule already selected: {state.get('scheduled_for')}, transitioning to SAVE_CONTENT")
                    state["current_step"] = ConversationStep.SAVE_CONTENT
                    result = state
                else:
                    # Only call select_schedule if we haven't already asked for schedule
                    # Check if we already have a schedule selection message
                    last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
                    # Don't add schedule message - UI will handle it
                    logger.info(f"SELECT_SCHEDULE step - UI will handle display")
                    # Call select_schedule to set the step, but it won't add a message
                    result = await self.select_schedule(state)
            elif current_step == ConversationStep.EDIT_IMAGE:
                result = await self.edit_image(state)
            elif current_step == ConversationStep.SAVE_CONTENT:
                result = await self.save_content(state)
                # After saving content, automatically transition to ask_another_content
                if result.get("current_step") == ConversationStep.ASK_ANOTHER_CONTENT:
                    result = await self.ask_another_content(result)
            elif current_step == ConversationStep.ASK_ANOTHER_CONTENT:
                # Check if user has already responded (processed in process_user_input)
                # If user wants to create another, current_step will be ASK_PLATFORM
                # If user is done, is_complete will be True
                if state.get("current_step") == ConversationStep.ASK_PLATFORM:
                    # User wants to create another - transition to platform selection
                    result = await self.ask_platform(state)
                elif state.get("is_complete", False):
                    # User is done - return state as is (will end conversation)
                    result = state
                else:
                    # Only call ask_another_content if we haven't already asked
                    # Check if we already have an ask another content message
                    last_message = state["conversation_messages"][-1] if state["conversation_messages"] else None
                    another_content_message = "Your post has been saved to the schedule section! 🎉\n\nWant to create another post or are you done for now?"
                    
                    if not last_message or another_content_message not in last_message.get("content", ""):
                        result = await self.ask_another_content(state)
                    else:
                        # Already asked about another content, just return current state
                        result = state
            elif current_step == ConversationStep.DISPLAY_RESULT:
                result = await self.display_result(state)
            elif current_step == ConversationStep.ERROR:
                result = await self.handle_error(state)
            else:
                # Default to current state if step is not recognized
                result = state
            
            # After executing any step, if result has current_step = PREVIEW_AND_EDIT but no preview message exists,
            # automatically call preview_and_edit to add the preview message
            # This ensures preview is shown immediately after content generation without waiting for user input
            if result.get("current_step") == ConversationStep.PREVIEW_AND_EDIT:
                has_preview_msg = any(msg.get("preview_mode") for msg in result.get("conversation_messages", []))
                if not has_preview_msg:
                    logger.info("No preview message found after step execution, automatically calling preview_and_edit")
                    result = await self.preview_and_edit(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing conversation step: {e}")
            state["error_message"] = f"Failed to execute conversation step: {str(e)}"
            state["current_step"] = ConversationStep.ERROR
            return state
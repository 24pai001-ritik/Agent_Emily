"""
Intent-Based Chatbot Agent using LangGraph and Pydantic
Handles user queries by classifying intent and routing to appropriate tools
"""

import os
import json
import logging
import re
from typing import Dict, List, Any, Optional, Literal, TypedDict
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from supabase import create_client, Client
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv
from services.token_usage_service import TokenUsageService

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Initialize OpenAI
openai_api_key = os.getenv("OPENAI_API_KEY")
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    openai_api_key=openai_api_key
)

logger = logging.getLogger(__name__)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

# -----------------------------------------------------------------------------
# SOCIAL MEDIA
# -----------------------------------------------------------------------------

class SocialMediaPayload(BaseModel):
    platform: Optional[List[Literal[
        "facebook",
        "instagram",
        "youtube",
        "linkedin",
        "twitter",
        "pinterest"
    ]]] = None

    content_type: Optional[Literal["post", "reel", "video", "story", "carousel"]] = None
    idea: Optional[str] = None

    media: Optional[Literal["upload", "generate"]] = None
    media_file: Optional[str] = None

    date: Optional[datetime] = None
    task: Optional[Literal["draft", "schedule", "edit", "delete"]] = None
    content: Optional[str] = None  # Content ID from created_content table after generation

# -----------------------------------------------------------------------------
# BLOG
# -----------------------------------------------------------------------------

class BlogPayload(BaseModel):
    platform: Optional[Literal["wordpress", "shopify", "wix", "html"]] = None
    topic: Optional[str] = None
    length: Optional[Literal["short", "medium", "long"]] = None

    media: Optional[Literal["generate", "upload"]] = None
    media_file: Optional[str] = None

    date: Optional[datetime] = None
    task: Optional[Literal["draft", "schedule", "save"]] = None

# -----------------------------------------------------------------------------
# EMAIL
# -----------------------------------------------------------------------------

class EmailPayload(BaseModel):
    email_address: Optional[EmailStr] = None
    content: Optional[str] = None

    attachments: Optional[List[str]] = None

    task: Optional[Literal["send", "save", "schedule"]] = None
    date: Optional[datetime] = None

# -----------------------------------------------------------------------------
# WHATSAPP MESSAGE
# -----------------------------------------------------------------------------

class WhatsAppPayload(BaseModel):
    phone_number: Optional[str] = Field(
        default=None,
        description="Phone number with country code, e.g. +919876543210"
    )

    text: Optional[str] = None
    attachment: Optional[str] = None

    task: Optional[Literal["send", "schedule", "save"]] = None
    date: Optional[datetime] = None

# -----------------------------------------------------------------------------
# ADS
# -----------------------------------------------------------------------------

class AdsPayload(BaseModel):
    platform: Optional[Literal["meta", "google", "linkedin", "youtube"]] = None
    objective: Optional[str] = None
    audience: Optional[str] = None
    budget: Optional[str] = None
    creative: Optional[str] = None

    date: Optional[datetime] = None
    task: Optional[Literal["draft", "schedule", "launch"]] = None

# -----------------------------------------------------------------------------
# CONTENT GENERATION
# -----------------------------------------------------------------------------

class ContentGenerationPayload(BaseModel):
    type: Literal["social_media", "blog", "email", "whatsapp", "ads"]

    social_media: Optional[SocialMediaPayload] = None
    blog: Optional[BlogPayload] = None
    email: Optional[EmailPayload] = None
    whatsapp: Optional[WhatsAppPayload] = None
    ads: Optional[AdsPayload] = None

# =============================================================================
# ANALYTICS
# =============================================================================

class AnalyticsPayload(BaseModel):
    # User wants INSIGHT or IMPROVEMENT?
    insight_type: Literal["insight", "improvement"]

    # Source of analytics
    source: Literal["social_media", "blog"]

    # SOCIAL MEDIA FIELDS
    platform: Optional[List[Literal[
        "instagram",
        "facebook",
        "youtube",
        "linkedin",
        "twitter",
        "pinterest"
    ]]] = None

    metrics: Optional[List[Literal[
        # Social media metrics
        "reach",
        "impressions",
        "engagement",
        "likes",
        "comments",
        "shares",
        "saves",
        "views",
        "profile_visits",
        "followers",
        "avg_view_time",
        "average_watch_time",
        "watch_time",
        "growth",
        "top_posts",
        "all_posts"   # for "saare posts"
    ]]] = None

    # BLOG METRICS
    blog_metrics: Optional[List[Literal[
        "views",
        "read_time",
        "bounce_rate",
        "engagement",
        "traffic_sources",
        "top_articles",
        "all_articles"  # optional aggregate
    ]]] = None

    # Applied to BOTH social + blog
    date_range: Optional[str] = None

# =============================================================================
# LEADS MANAGEMENT
# =============================================================================

class LeadsManagementPayload(BaseModel):
    action: Optional[
        Literal[
            "add_lead",
            "update_lead",
            "search_lead",
            "export_leads",
            "inquire_status",
            "inquire_status_summary"
        ]
    ] = None

    # For individual lead operations
    lead_name: Optional[str] = None
    lead_email: Optional[EmailStr] = None
    lead_phone: Optional[str] = None
    notes: Optional[str] = None
    lead_id: Optional[str] = None

    # For individual lead status questions
    status_query: Optional[str] = Field(
        default=None,
        description="User asking about a specific lead's status"
    )

    # For summary inquiries
    status_type: Optional[
        Literal[
            "new",
            "contacted",
            "responded",
            "qualified",
            "invalid",
            "lost",
            "converted",
            "followup"
        ]
    ] = Field(
        default=None,
        description="Lead pipeline stage for summary inquiry"
    )

    # Optional time filter
    date_range: Optional[str] = Field(
        default=None,
        description="Example: today, yesterday, last 7 days, this week, last month"
    )

# =============================================================================
# POSTING MANAGER
# =============================================================================

class PostingManagerPayload(BaseModel):
    platform: Optional[str] = None
    action: Optional[Literal["view_queue", "update_post", "delete_post"]] = None
    post_id: Optional[str] = None

# =============================================================================
# GENERAL TALK
# =============================================================================

class GeneralTalkPayload(BaseModel):
    message: Optional[str] = None

# =============================================================================
# TOP-LEVEL INTENT PAYLOAD
# =============================================================================

class IntentPayload(BaseModel):
    intent: Literal[
        "content_generation",
        "analytics",
        "leads_management",
        "posting_manager",
        "general_talks"
    ]

    content: Optional[ContentGenerationPayload] = None
    analytics: Optional[AnalyticsPayload] = None
    leads: Optional[LeadsManagementPayload] = None
    posting: Optional[PostingManagerPayload] = None
    general: Optional[GeneralTalkPayload] = None

# Rebuild forward references
IntentPayload.model_rebuild()
ContentGenerationPayload.model_rebuild()

# =============================================================================
# LANGGRAPH STATE
# =============================================================================

class IntentBasedChatbotState(TypedDict):
    """State for the intent-based chatbot conversation"""
    user_id: str
    current_query: str
    conversation_history: Optional[List[Dict[str, str]]]
    intent_payload: Optional[IntentPayload]  # The classified payload
    partial_payload: Optional[Dict[str, Any]]  # Accumulated partial payload data
    response: Optional[str]
    context: Dict[str, Any]
    needs_clarification: Optional[bool]  # Whether we're waiting for user input
    options: Optional[List[str]]  # Clickable options for user selection
    content_data: Optional[Dict[str, Any]]  # Structured content data (title, content, hashtags, images)

# =============================================================================
# INTENT-BASED CHATBOT CLASS
# =============================================================================

class IntentBasedChatbot:
    # Platform aliases mapping
    PLATFORM_ALIASES = {
        "insta": "instagram",
        "ig": "instagram",
        "fb": "facebook",
        "yt": "youtube",
        "ytube": "youtube",
        "x": "twitter",
        "linkedin": "linkedin",
        "pinterest": "pinterest",
        "pin": "pinterest"
    }
    
    # Valid platform names
    VALID_PLATFORMS = ["instagram", "facebook", "youtube", "linkedin", "twitter", "pinterest"]
    
    # Valid social media metrics
    VALID_SOCIAL_METRICS = [
        "reach", "impressions", "engagement", "likes", "comments", "shares",
        "saves", "views", "profile_visits", "followers", "avg_view_time",
        "average_watch_time", "watch_time", "growth", "top_posts", "all_posts"
    ]
    
    # Metric synonyms mapping
    METRIC_SYNONYMS = {
        "profile visit": "profile_visits",
        "profile visits": "profile_visits",
        "avg view time": "avg_view_time",
        "average view time": "avg_view_time",
        "watch time": "watch_time",
        "average watch time": "average_watch_time",
        "top post": "top_posts",
        "top posts": "top_posts",
        "all post": "all_posts",
        "all posts": "all_posts",
        "saare posts": "all_posts"
    }
    
    # Valid blog metrics
    VALID_BLOG_METRICS = [
        "views", "read_time", "bounce_rate", "engagement",
        "traffic_sources", "top_articles", "all_articles"
    ]
    
    def __init__(self):
        self.llm = llm
        # Initialize token tracker for usage tracking
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if supabase_url and supabase_service_key:
            self.token_tracker = TokenUsageService(supabase_url, supabase_service_key)
        else:
            self.token_tracker = None
        self.setup_graph()
    
    def setup_graph(self):
        """Setup the LangGraph workflow"""
        workflow = StateGraph(IntentBasedChatbotState)
        
        # Add nodes
        workflow.add_node("classify_intent", self.classify_intent)
        workflow.add_node("handle_content_generation", self.handle_content_generation)
        workflow.add_node("handle_analytics", self.handle_analytics)
        workflow.add_node("handle_leads_management", self.handle_leads_management)
        workflow.add_node("handle_posting_manager", self.handle_posting_manager)
        workflow.add_node("handle_general_talks", self.handle_general_talks)
        workflow.add_node("generate_final_response", self.generate_final_response)
        
        # Set entry point
        workflow.set_entry_point("classify_intent")
        
        # Conditional routing based on intent
        workflow.add_conditional_edges(
            "classify_intent",
            self.route_by_intent,
            {
                "content_generation": "handle_content_generation",
                "analytics": "handle_analytics",
                "leads_management": "handle_leads_management",
                "posting_manager": "handle_posting_manager",
                "general_talks": "handle_general_talks"
            }
        )
        
        # All handlers go to generate_final_response
        workflow.add_edge("handle_content_generation", "generate_final_response")
        workflow.add_edge("handle_analytics", "generate_final_response")
        workflow.add_edge("handle_leads_management", "generate_final_response")
        workflow.add_edge("handle_posting_manager", "generate_final_response")
        workflow.add_edge("handle_general_talks", "generate_final_response")
        workflow.add_edge("generate_final_response", END)
        
        # Compile the graph
        self.graph = workflow.compile()
    
    def route_by_intent(self, state: IntentBasedChatbotState) -> str:
        """Route to appropriate handler based on intent"""
        if not state.get("intent_payload"):
            return "general_talks"
        return state["intent_payload"].intent
    
    def _normalize_payload(self, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize and fix payload structure before validation.
        
        FIX 6: Never overwrite existing valid fields.
        """
        # Fix analytics payload field mappings using comprehensive normalization
        if payload_dict.get("intent") == "analytics" and payload_dict.get("analytics"):
            analytics = payload_dict["analytics"]
            if isinstance(analytics, dict):
                # Use comprehensive normalization utility (user_query not available here, but that's OK)
                normalized_analytics = self._normalize_analytics_payload(analytics, user_query=None)
                # FIX 6: Merge normalized fields but preserve existing valid fields
                for key, value in normalized_analytics.items():
                    if value is not None:
                        existing_value = analytics.get(key)
                        # Preserve existing valid values
                        if key == "insight_type" and existing_value in ["insight", "improvement"]:
                            continue
                        elif key == "source" and existing_value in ["social_media", "blog"]:
                            continue
                        elif key in ["platform", "metrics", "blog_metrics"] and existing_value and isinstance(existing_value, list) and len(existing_value) > 0:
                            continue  # Preserve existing valid lists
                        else:
                            analytics[key] = value
                
                # Remove old fields that were normalized (only if they're not the canonical field)
                analytics.pop("type", None)
                analytics.pop("analysis_type", None)
                analytics.pop("mode", None)
                analytics.pop("analytics_type", None)
                analytics.pop("insight", None)
                analytics.pop("preference", None)
                analytics.pop("metric", None)
                analytics.pop("metric_type", None)
                analytics.pop("blog_metric", None)
                
                payload_dict["analytics"] = analytics
                logger.info(f"Normalized analytics payload: {json.dumps(analytics, indent=2, default=str)}")
        
        # Fix content_generation payload if type is missing or null
        if payload_dict.get("intent") == "content_generation" and payload_dict.get("content"):
            content = payload_dict["content"]
            
            if isinstance(content, dict):
                # Check if type is missing, None, or null
                content_type = content.get("type")
                
                # Handle None/null values
                if content_type is None or content_type == "null" or content_type == "":
                    content_type = None
                
                # If type is missing or null, try to infer it
                if not content_type:
                    # Try to infer type from existing nested objects
                    if content.get("social_media"):
                        content["type"] = "social_media"
                        content_type = "social_media"
                    elif content.get("blog"):
                        content["type"] = "blog"
                        content_type = "blog"
                    elif content.get("email"):
                        content["type"] = "email"
                        content_type = "email"
                    elif content.get("whatsapp"):
                        content["type"] = "whatsapp"
                        content_type = "whatsapp"
                    elif content.get("ads"):
                        content["type"] = "ads"
                        content_type = "ads"
                    else:
                        # Check for blog-like fields (topic, length, style) - these suggest blog type
                        if any(key in content for key in ["topic", "length", "style"]):
                            # These fields suggest it might be a blog, but we need to restructure
                            # For now, default to social_media as it's most common
                            content["type"] = "social_media"
                            content_type = "social_media"
                            logger.warning("Content type missing, detected blog-like fields but defaulting to social_media")
                        else:
                            # Default to social_media if we can't infer (most common use case)
                            # This handles the case where user says "create content" without specifying type
                            content["type"] = "social_media"
                            content_type = "social_media"
                            logger.warning("Content type missing or null, defaulting to social_media")
                
                # If we have social_media type, ensure social_media nested object exists
                if content_type == "social_media":
                    if "social_media" not in content:
                        content["social_media"] = {}
                    
                    social_media = content["social_media"]
                    if not isinstance(social_media, dict):
                        social_media = {}
                        content["social_media"] = social_media
                    
                    # Check if platform or content_type are at the wrong level (directly under content)
                    # Move them to social_media if found
                    if "platform" in content and "platform" not in social_media:
                        social_media["platform"] = content.pop("platform")
                        logger.info(f"Moved platform from content to social_media: {social_media.get('platform')}")
                    
                    if "content_type" in content and "content_type" not in social_media:
                        social_media["content_type"] = content.pop("content_type")
                        logger.info(f"Moved content_type from content to social_media: {social_media.get('content_type')}")
                    
                    if "idea" in content and "idea" not in social_media:
                        social_media["idea"] = content.pop("idea")
                        logger.info(f"Moved idea from content to social_media: {social_media.get('idea')}")
                    
                    # Move media and media_file fields if they're at the wrong level
                    if "media" in content and "media" not in social_media:
                        social_media["media"] = content.pop("media")
                        logger.info(f"Moved media from content to social_media: {social_media.get('media')}")
                    
                    if "media_file" in content and "media_file" not in social_media:
                        social_media["media_file"] = content.pop("media_file")
                        logger.info(f"Moved media_file from content to social_media: {social_media.get('media_file')}")
                    
                    # Move date and task fields if they're at the wrong level
                    if "date" in content and "date" not in social_media:
                        social_media["date"] = content.pop("date")
                        logger.info(f"Moved date from content to social_media: {social_media.get('date')}")
                    
                    if "task" in content and "task" not in social_media:
                        social_media["task"] = content.pop("task")
                        logger.info(f"Moved task from content to social_media: {social_media.get('task')}")
                    
                    # Move content field (for saved_content_id) if it's at the wrong level
                    if "content" in content and "content" not in social_media:
                        social_media["content"] = content.pop("content")
                        logger.info(f"Moved content (saved_content_id) from content to social_media: {social_media.get('content')}")
                
                # If we have email type, ensure email nested object exists and normalize field names
                elif content_type == "email":
                    if "email" not in content:
                        content["email"] = {}
                    
                    email = content["email"]
                    if not isinstance(email, dict):
                        email = {}
                        content["email"] = email
                    
                    # Map common field name variations to the correct field name
                    # LLM might use "recipient" but EmailPayload uses "email_address"
                    if "recipient" in email and "email_address" not in email:
                        email["email_address"] = email.pop("recipient")
                        logger.info(f"Mapped recipient to email_address: {email.get('email_address')}")
                    
                    # Also check if recipient is at the wrong level (directly under content)
                    if "recipient" in content and "email_address" not in email:
                        email["email_address"] = content.pop("recipient")
                        logger.info(f"Moved recipient from content to email.email_address: {email.get('email_address')}")
                    
                    # Map common email content field name variations
                    # LLM might use "body", "message", "text", "subject" but EmailPayload uses "content"
                    content_field_aliases = ["body", "message", "text", "subject", "topic", "about"]
                    for alias in content_field_aliases:
                        if alias in email and "content" not in email:
                            email["content"] = email.pop(alias)
                            logger.info(f"Mapped {alias} to content: {email.get('content')[:50] if email.get('content') else None}")
                            break
                        elif alias in content and "content" not in email:
                            email["content"] = content.pop(alias)
                            logger.info(f"Moved {alias} from content to email.content: {email.get('content')[:50] if email.get('content') else None}")
                            break
                    
                    # Handle attachment/attachments fields
                    # EmailPayload uses "attachments" (plural, List[str])
                    # LLM might use "attachment" (singular) - convert to list if needed
                    if "attachment" in email and "attachments" not in email:
                        attachment_value = email.pop("attachment")
                        # Convert to list if it's a string
                        if isinstance(attachment_value, str):
                            email["attachments"] = [attachment_value]
                        elif isinstance(attachment_value, list):
                            email["attachments"] = attachment_value
                        else:
                            email["attachments"] = [str(attachment_value)] if attachment_value else []
                        logger.info(f"Mapped attachment to attachments: {email.get('attachments')}")
                    
                    # Also check if attachment/attachments is at the wrong level (directly under content)
                    if "attachment" in content and "attachments" not in email:
                        attachment_value = content.pop("attachment")
                        if isinstance(attachment_value, str):
                            email["attachments"] = [attachment_value]
                        elif isinstance(attachment_value, list):
                            email["attachments"] = attachment_value
                        else:
                            email["attachments"] = [str(attachment_value)] if attachment_value else []
                        logger.info(f"Moved attachment from content to email.attachments: {email.get('attachments')}")
                    
                    if "attachments" in content and "attachments" not in email:
                        email["attachments"] = content.pop("attachments")
                        logger.info(f"Moved attachments from content to email.attachments: {email.get('attachments')}")
                
                # If we have blog type, ensure blog nested object exists and normalize field names
                elif content_type == "blog":
                    if "blog" not in content:
                        content["blog"] = {}
                    
                    blog = content["blog"]
                    if not isinstance(blog, dict):
                        blog = {}
                        content["blog"] = blog
                    
                    # Check if blog fields are at the wrong level (directly under content)
                    # Move them to blog if found
                    blog_field_mappings = {
                        "topic": "topic",
                        "platform": "platform",
                        "length": "length",
                        "media": "media",
                        "media_file": "media_file",
                        "task": "task"
                    }
                    for field_name, target_field in blog_field_mappings.items():
                        if field_name in content and target_field not in blog:
                            blog[target_field] = content.pop(field_name)
                            logger.info(f"Moved {field_name} from content to blog.{target_field}: {blog.get(target_field)}")
                
                # If we have whatsapp type, ensure whatsapp nested object exists and normalize field names
                elif content_type == "whatsapp":
                    if "whatsapp" not in content:
                        content["whatsapp"] = {}
                    
                    whatsapp = content["whatsapp"]
                    if not isinstance(whatsapp, dict):
                        whatsapp = {}
                        content["whatsapp"] = whatsapp
                    
                    # Map common field name variations
                    # LLM might use "phone" or "number" but WhatsAppPayload uses "phone_number"
                    if "phone" in whatsapp and "phone_number" not in whatsapp:
                        whatsapp["phone_number"] = whatsapp.pop("phone")
                        logger.info(f"Mapped phone to phone_number: {whatsapp.get('phone_number')}")
                    
                    if "number" in whatsapp and "phone_number" not in whatsapp:
                        whatsapp["phone_number"] = whatsapp.pop("number")
                        logger.info(f"Mapped number to phone_number: {whatsapp.get('phone_number')}")
                    
                    # Also check if phone/number is at the wrong level (directly under content)
                    if "phone" in content and "phone_number" not in whatsapp:
                        whatsapp["phone_number"] = content.pop("phone")
                        logger.info(f"Moved phone from content to whatsapp.phone_number: {whatsapp.get('phone_number')}")
                    
                    if "number" in content and "phone_number" not in whatsapp:
                        whatsapp["phone_number"] = content.pop("number")
                        logger.info(f"Moved number from content to whatsapp.phone_number: {whatsapp.get('phone_number')}")
                    
                    # Map common message field name variations
                    # LLM might use "message", "text", "content" but WhatsAppPayload uses "text"
                    message_field_aliases = ["message", "content", "body"]
                    for alias in message_field_aliases:
                        if alias in whatsapp and "text" not in whatsapp:
                            whatsapp["text"] = whatsapp.pop(alias)
                            logger.info(f"Mapped {alias} to text: {whatsapp.get('text')[:50] if whatsapp.get('text') else None}")
                            break
                        elif alias in content and "text" not in whatsapp:
                            whatsapp["text"] = content.pop(alias)
                            logger.info(f"Moved {alias} from content to whatsapp.text: {whatsapp.get('text')[:50] if whatsapp.get('text') else None}")
                            break
                    
                    # Handle attachment field
                    # WhatsAppPayload uses "attachment" (singular, str)
                    if "attachment" in content and "attachment" not in whatsapp:
                        whatsapp["attachment"] = content.pop("attachment")
                        logger.info(f"Moved attachment from content to whatsapp.attachment: {whatsapp.get('attachment')}")
                
                # Re-check content_type after inference (it should be set by now)
                content_type = content.get("type")
                logger.info(f"Content type after inference: {content_type}")
                
                # Ensure type is valid (handle case where type was set but invalid)
                if content_type and content_type not in [None, "null", ""]:
                    valid_types = ["social_media", "blog", "email", "whatsapp", "ads"]
                    if content_type not in valid_types:
                        logger.warning(f"Invalid content type '{content_type}', defaulting to social_media")
                        content["type"] = "social_media"
                        content_type = "social_media"
                    
                    # If type is set but the corresponding nested object doesn't exist, create an empty one
                    # This ensures the payload structure is valid for validation
                    if content_type == "social_media" and "social_media" not in content:
                        content["social_media"] = {}
                    elif content_type == "blog" and "blog" not in content:
                        content["blog"] = {}
                    elif content_type == "email" and "email" not in content:
                        content["email"] = {}
                    elif content_type == "whatsapp" and "whatsapp" not in content:
                        content["whatsapp"] = {}
                    elif content_type == "ads" and "ads" not in content:
                        content["ads"] = {}
                else:
                    # If type is still None/empty after all attempts, remove the content object entirely
                    # We'll ask the user for the type in the handler
                    logger.warning(f"Content type could not be determined (type={content_type}), removing content from payload")
                    payload_dict["content"] = None
                    # Return early since we've removed content
                    return payload_dict
                
                # Remove invalid fields that don't belong in ContentGenerationPayload
                # ContentGenerationPayload should only have: type, social_media, blog, email, whatsapp, ads
                # Only do this if content still exists and has a valid type
                if content and isinstance(content, dict) and content.get("type"):
                    valid_content_keys = ["type", "social_media", "blog", "email", "whatsapp", "ads"]
                    invalid_keys = [key for key in content.keys() if key not in valid_content_keys]
                    if invalid_keys:
                        logger.warning(f"Removing invalid fields from content payload: {invalid_keys}")
                        for key in invalid_keys:
                            content.pop(key, None)
                elif content and isinstance(content, dict) and not content.get("type"):
                    # If content exists but type is still None, remove it
                    logger.warning("Content object exists but type is None, removing content from payload")
                    payload_dict["content"] = None
        
        return payload_dict
    
    def _merge_payloads(self, existing: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge new payload data into existing partial payload.
        
        FIX 2: New non-null values override old ones, empty lists do NOT count as valid.
        FIX 6: Properly merge nested dicts without overwriting valid existing fields.
        For analytics, new values always override old ones (except when old value is valid and new is invalid).
        """
        if not existing:
            return new.copy()
        
        merged = existing.copy()
        
        # Recursively merge nested dictionaries
        for key, value in new.items():
            if value is not None:  # Only merge non-null values
                # FIX 2: Empty lists do NOT count as valid values - skip them
                if isinstance(value, list) and len(value) == 0:
                    continue
                
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    # Special handling for analytics dict
                    if key == "analytics":
                        # Merge analytics dict - new values override old ones
                        merged_analytics = merged[key].copy()
                        for analytics_key, analytics_value in value.items():
                            if analytics_value is not None:
                                # FIX 2: Empty lists don't override existing values
                                if isinstance(analytics_value, list) and len(analytics_value) == 0:
                                    continue
                                
                                # FIX 2: New non-null values always override old ones
                                # Special case: preserve valid existing values only if new value is invalid
                                existing_analytics_value = merged_analytics.get(analytics_key)
                                
                                if analytics_key == "insight_type":
                                    if analytics_value in ["insight", "improvement"]:
                                        merged_analytics[analytics_key] = analytics_value
                                    # If new value is invalid but old is valid, keep old
                                    elif existing_analytics_value in ["insight", "improvement"]:
                                        continue  # Keep existing valid value
                                    else:
                                        merged_analytics[analytics_key] = analytics_value
                                elif analytics_key == "source":
                                    if analytics_value in ["social_media", "blog"]:
                                        merged_analytics[analytics_key] = analytics_value
                                    # If new value is invalid but old is valid, keep old
                                    elif existing_analytics_value in ["social_media", "blog"]:
                                        continue  # Keep existing valid value
                                    else:
                                        merged_analytics[analytics_key] = analytics_value
                                else:
                                    # For other fields, new value always overrides
                                    merged_analytics[analytics_key] = analytics_value
                        merged[key] = merged_analytics
                    else:
                        # Regular nested dict merge
                        merged[key] = self._merge_payloads(merged[key], value)
                else:
                    # Update top-level or non-dict values
                    # FIX 2: Empty lists don't override existing values
                    if isinstance(value, list) and len(value) == 0:
                        continue
                    merged[key] = value
        
        return merged
    
    def _normalize_platform(self, platform: Any) -> Optional[str]:
        """Normalize platform name to valid enum value"""
        if platform is None:
            return None
        
        if isinstance(platform, list):
            if len(platform) == 0:
                return None
            platform = platform[0]
        
        platform_str = str(platform).strip().lower()
        
        if platform_str in self.PLATFORM_ALIASES:
            platform_str = self.PLATFORM_ALIASES[platform_str]
        
        if platform_str in self.VALID_PLATFORMS:
            return platform_str
        
        logger.warning(f"Invalid platform: {platform}, normalized to None")
        return None
    
    def _normalize_platform_list(self, platforms: Any) -> List[str]:
        """Normalize a list of platforms to valid enum values"""
        if platforms is None:
            return []
        
        if isinstance(platforms, str):
            platforms = [platforms]
        
        if not isinstance(platforms, list):
            platforms = [platforms]
        
        normalized = []
        for p in platforms:
            norm_p = self._normalize_platform(p)
            if norm_p and norm_p not in normalized:
                normalized.append(norm_p)
        
        return normalized
    
    def _normalize_metric(self, metric: str) -> Optional[str]:
        """Normalize a single metric name to valid enum value"""
        if not metric:
            return None
        
        metric_str = str(metric).strip().lower()
        
        if metric_str in self.METRIC_SYNONYMS:
            metric_str = self.METRIC_SYNONYMS[metric_str]
        
        if metric_str in self.VALID_SOCIAL_METRICS:
            return metric_str
        
        logger.warning(f"Invalid metric: {metric}, normalized to None")
        return None
    
    def _normalize_metrics(self, metrics: Any) -> List[str]:
        """Normalize metrics list to valid enum values"""
        if metrics is None:
            return []
        
        # Handle string input (comma-separated or single value)
        if isinstance(metrics, str):
            metrics_str = metrics.strip()
            if not metrics_str:
                return []
            if "," in metrics_str:
                metrics = [m.strip() for m in metrics_str.split(",")]
            else:
                metrics = [metrics_str]
        
        # Convert non-list to list
        if not isinstance(metrics, list):
            metrics = [metrics]
        
        # Normalize each metric and remove duplicates
        normalized = []
        for m in metrics:
            if m is None:
                continue
            norm_m = self._normalize_metric(m)
            if norm_m and norm_m not in normalized:
                normalized.append(norm_m)
        
        return normalized
    
    def _normalize_blog_metrics(self, metrics: Any) -> List[str]:
        """Normalize blog metrics list to valid enum values"""
        if metrics is None:
            return []
        
        # Handle string input (comma-separated or single value)
        if isinstance(metrics, str):
            metrics_str = metrics.strip()
            if not metrics_str:
                return []
            if "," in metrics_str:
                metrics = [m.strip() for m in metrics_str.split(",")]
            else:
                metrics = [metrics_str]
        
        # Convert non-list to list
        if not isinstance(metrics, list):
            metrics = [metrics]
        
        # Normalize each metric and remove duplicates
        normalized = []
        for m in metrics:
            if m is None:
                continue
            m_str = str(m).strip().lower()
            if m_str in self.VALID_BLOG_METRICS and m_str not in normalized:
                normalized.append(m_str)
        
        return normalized
    
    def _normalize_insight_type(self, insight_type: Any) -> Optional[str]:
        """
        Normalize insight_type to valid enum value.
        
        Handles multiple input formats:
        - String: "insight", "improvement"
        - List: ["insight"], ["improvement"]
        - Nested dict: {"type": "insight"}
        - Various synonyms and aliases
        """
        if insight_type is None:
            return None
        
        # Handle list - take first element
        if isinstance(insight_type, list):
            if len(insight_type) == 0:
                return None
            insight_type = insight_type[0]
        
        # Handle dict - extract value
        if isinstance(insight_type, dict):
            # Try common keys
            insight_type = (
                insight_type.get("type") or
                insight_type.get("value") or
                insight_type.get("insight_type") or
                list(insight_type.values())[0] if insight_type else None
            )
            if insight_type is None:
                return None
        
        # Convert to string and normalize
        insight_str = str(insight_type).strip().lower()
        
        # Map synonyms to canonical values
        if insight_str in ["insight", "insights", "analyze", "analysis", "analytics"]:
            return "insight"
        
        if insight_str in ["improvement", "improve", "suggestions", "suggestion", "recommendations", "suggest"]:
            return "improvement"
        
        logger.warning(f"Invalid insight_type: {insight_type}, normalized to None")
        return None
    
    def _normalize_source(self, source: Any) -> Optional[str]:
        """Normalize source to valid enum value"""
        if source is None:
            return None
        
        source_str = str(source).strip().lower()
        
        if source_str in ["social_media", "social", "social media", "sns"]:
            return "social_media"
        
        if source_str in ["blog", "blogs", "blogging"]:
            return "blog"
        
        logger.warning(f"Invalid source: {source}, normalized to None")
        return None
    
    def _normalize_analytics_payload(self, analytics_dict: Dict[str, Any], user_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive normalization of analytics payload from LLM.
        
        FIX 1: Strong canonical mapping for insight_type from multiple variants.
        FIX 3: Platform implies source - if platform provided, auto-assign source.
        FIX 6: Never overwrite existing valid fields.
        
        Args:
            analytics_dict: The analytics dictionary to normalize
            user_query: Optional user query to help with normalization when LLM extraction fails
        """
        if not analytics_dict:
            return {}
        
        normalized = {}
        
        # FIX 1: Strong canonical mapping for insight_type
        # Check multiple possible keys that might contain insight_type
        insight_type = (
            analytics_dict.get("insight_type") or
            analytics_dict.get("type") or
            analytics_dict.get("analysis_type") or
            analytics_dict.get("mode") or
            analytics_dict.get("analytics_type") or
            analytics_dict.get("insight") or
            analytics_dict.get("preference")
        )
        
        # FIX 1: Also check user_query if provided (fallback when LLM extraction fails)
        if not insight_type and user_query:
            user_query_lower = user_query.strip().lower()
            if user_query_lower in ["insight", "improvement"]:
                insight_type = user_query_lower
                logger.info(f"FIX 1: Extracted insight_type from user_query fallback: {insight_type}")
        
        # FIX 6: Only normalize if not already present and valid
        existing_insight_type = analytics_dict.get("insight_type")
        if existing_insight_type and existing_insight_type in ["insight", "improvement"]:
            # Already valid, don't override
            normalized["insight_type"] = existing_insight_type
            logger.info(f"Preserving existing valid insight_type: {existing_insight_type}")
        else:
            # Normalize from extracted value
            normalized["insight_type"] = self._normalize_insight_type(insight_type)
        
        # 2. Normalize source (FIX 3: platform implies source, FIX 6: preserve if valid)
        existing_source = analytics_dict.get("source")
        if existing_source and existing_source in ["social_media", "blog"]:
            normalized["source"] = existing_source
        else:
            # FIX 3: Check if platform implies source
            platform = analytics_dict.get("platform")
            inferred_source = None
            
            if platform:
                # Handle both list and single platform
                platform_list = platform if isinstance(platform, list) else [platform] if platform else []
                # Filter out None/empty values and normalize
                platform_list = [str(p).strip().lower() for p in platform_list if p]
                
                if platform_list:  # Only proceed if we have valid platforms
                    # Social media platforms
                    social_media_platforms = ["instagram", "facebook", "twitter", "youtube", "linkedin", "tiktok", "snapchat", "pinterest"]
                    # Blog platforms
                    blog_platforms = ["wordpress", "medium", "substack", "blogger"]
                    
                    # Check if any platform is a social media platform
                    has_social_media = any(p in social_media_platforms for p in platform_list)
                    # Check if any platform is a blog platform
                    has_blog = any(p in blog_platforms for p in platform_list)
                    
                    # Priority: social_media platforms take precedence if mixed
                    if has_social_media:
                        inferred_source = "social_media"
                        logger.info(f"FIX 3: Platform {platform_list} implies source='social_media'")
                    elif has_blog:
                        inferred_source = "blog"
                        logger.info(f"FIX 3: Platform {platform_list} implies source='blog'")
            
            # Use inferred source if available, otherwise normalize from source field
            if inferred_source:
                normalized["source"] = inferred_source
            else:
                # CRITICAL FIX: If source was already set by direct answer detection, preserve it
                # Don't normalize it away if it's already valid
                if existing_source and existing_source in ["social_media", "blog"]:
                    normalized["source"] = existing_source
                else:
                    normalized["source"] = self._normalize_source(analytics_dict.get("source"))
        
        # 3. Normalize platform (FIX 6: preserve if valid list)
        existing_platform = analytics_dict.get("platform")
        if existing_platform and isinstance(existing_platform, list) and len(existing_platform) > 0:
            # Already valid list, normalize but preserve structure
            normalized["platform"] = self._normalize_platform_list(existing_platform)
        elif existing_platform:
            normalized["platform"] = self._normalize_platform_list(existing_platform)
        else:
            platform = analytics_dict.get("platform")
            if platform:
                normalized["platform"] = self._normalize_platform_list(platform)
            else:
                normalized["platform"] = None
        
        # 4. Normalize metrics (FIX 6: preserve if valid list)
        existing_metrics = analytics_dict.get("metrics")
        if existing_metrics and isinstance(existing_metrics, list) and len(existing_metrics) > 0:
            # Already valid list, normalize but preserve
            normalized["metrics"] = self._normalize_metrics(existing_metrics)
        else:
            metrics = (
                analytics_dict.get("metrics") or
                analytics_dict.get("metric") or
                analytics_dict.get("metric_type")
            )
            if metrics:
                normalized["metrics"] = self._normalize_metrics(metrics)
            else:
                normalized["metrics"] = None
        
        # 5. Normalize blog_metrics (FIX 6: preserve if valid list)
        existing_blog_metrics = analytics_dict.get("blog_metrics")
        if existing_blog_metrics and isinstance(existing_blog_metrics, list) and len(existing_blog_metrics) > 0:
            normalized["blog_metrics"] = self._normalize_blog_metrics(existing_blog_metrics)
        else:
            blog_metrics = (
                analytics_dict.get("blog_metrics") or
                analytics_dict.get("blog_metric")
            )
            if blog_metrics:
                normalized["blog_metrics"] = self._normalize_blog_metrics(blog_metrics)
            else:
                normalized["blog_metrics"] = None
        
        # 6. Normalize date_range (FIX 6: preserve if valid)
        existing_date_range = analytics_dict.get("date_range")
        if existing_date_range and isinstance(existing_date_range, str) and existing_date_range.strip():
            normalized["date_range"] = existing_date_range.strip()
        else:
            date_range = analytics_dict.get("date_range")
            if date_range:
                normalized["date_range"] = str(date_range).strip()
            else:
                normalized["date_range"] = None
        
        # Remove None values to allow Pydantic defaults (but preserve empty lists as they indicate "provided but empty")
        normalized = {k: v for k, v in normalized.items() if v is not None}
        
        logger.info(f"Normalized analytics payload: {normalized}")
        return normalized
    
    def _get_missing_fields_for_social_media(self, payload: Any) -> List[Dict[str, Any]]:
        """Get list of missing required fields for social media payload"""
        missing = []
        
        if not payload:
            return [{
                "field": "platform", 
                "question": "Which platform(s) would you like to create content for?", 
                "options": ["facebook", "instagram", "youtube", "linkedin", "twitter", "pinterest"],
                "priority": 1
            }]
        
        # Required fields in priority order
        if not payload.platform:
            missing.append({
                "field": "platform",
                "question": "Which platform(s) would you like to create content for?",
                "options": ["facebook", "instagram", "youtube", "linkedin", "twitter", "pinterest"],
                "priority": 1
            })
        
        if not payload.content_type:
            missing.append({
                "field": "content_type",
                "question": "What type of content would you like to create?",
                "options": ["post", "reel", "video", "story", "carousel"],
                "priority": 2
            })
        
        if not payload.idea:
            missing.append({
                "field": "idea",
                "question": "What would you like to share in this social media post?",
                "options": None,
                "priority": 3
            })
        
        # Sort by priority
        missing.sort(key=lambda x: x.get("priority", 999))
        return missing
    
    def _get_missing_fields_for_analytics(self, analytics_dict: Dict[str, Any], user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get list of missing REQUIRED fields for analytics payload.
        
        FIX 3: Check for empty lists, not just None.
        FIX 4: Platform implies source - skip source question if platform provided.
        FIX 6: Don't overwrite existing valid fields.
        
        Emily ONLY checks for fields that MUST be provided by the user.
        All defaults, platform inference, and business logic is handled by Orion.
        
        Required fields checked:
        - insight_type: REQUIRED (priority 1)
        - source: REQUIRED (priority 2) - SKIPPED if platform implies source
        - platform: REQUIRED if multiple platforms connected or none connected (priority 3)
        - metrics: REQUIRED only for improvement mode with social_media (priority 4)
        - blog_metrics: REQUIRED only for improvement mode with blog (priority 4)
        
        NOT checked here (handled by Orion):
        - date_range (optional, Orion handles defaults)
        - metrics for insight mode (Orion applies defaults: ["reach", "impressions", "engagement"])
        - blog_metrics for insight mode (Orion applies defaults: ["views", "read_time", "top_articles"])
        """
        missing = []
        
        if not analytics_dict:
            return [{
                "field": "insight_type",
                "question": "I'd love to help you with analytics! Do you want insights about your performance, or suggestions for improvement?",
                "options": ["insight", "improvement"],
                "priority": 1
            }]
        
        # Get insight_type (already normalized)
        insight_type = analytics_dict.get("insight_type")
        
        # FIX 4: Priority 1: insight_type (REQUIRED) - check for None OR empty string
        if not insight_type or (isinstance(insight_type, str) and not insight_type.strip()):
            missing.append({
                "field": "insight_type",
                "question": "Do you want insights or improvements?",
                "options": ["insight", "improvement"],
                "priority": 1
            })
            # Return early - can't check other fields without insight_type
            return missing
        
        # FIX 4: Priority 2: source (REQUIRED) - check for None OR empty string
        # FIX 3: SKIP source question if platform implies source
        source = analytics_dict.get("source")
        platform = analytics_dict.get("platform")
        
        # FIX 3: Check if platform implies source
        platform_implies_source = False
        if platform:
            # Normalize platform to list format
            platform_list = platform if isinstance(platform, list) else [platform] if platform else []
            # Filter out None/empty values
            platform_list = [str(p).strip().lower() for p in platform_list if p]
            
            if platform_list:  # Only proceed if we have valid platforms
                social_media_platforms = ["instagram", "facebook", "twitter", "youtube", "linkedin", "tiktok", "snapchat", "pinterest"]
                blog_platforms = ["wordpress", "medium", "substack", "blogger"]
                
                # Check if any platform is a social media platform
                has_social_media = any(p in social_media_platforms for p in platform_list)
                # Check if any platform is a blog platform
                has_blog = any(p in blog_platforms for p in platform_list)
                
                # Priority: social_media platforms take precedence if mixed
                if has_social_media:
                    # Platform implies social_media source
                    if not source or source not in ["social_media", "blog"]:
                        # Auto-assign source
                        analytics_dict["source"] = "social_media"
                        source = "social_media"
                        platform_implies_source = True
                        logger.info(f"FIX 3: Platform {platform_list} implies source='social_media', auto-assigned")
                elif has_blog:
                    # Platform implies blog source
                    if not source or source not in ["social_media", "blog"]:
                        # Auto-assign source
                        analytics_dict["source"] = "blog"
                        source = "blog"
                        platform_implies_source = True
                        logger.info(f"FIX 3: Platform {platform_list} implies source='blog', auto-assigned")
        
        # Only ask for source if it's still missing after platform inference
        if not source or (isinstance(source, str) and not source.strip()):
            missing.append({
                "field": "source",
                "question": "Do you want social media analytics or blog analytics?",
                "options": ["social_media", "blog"],
                "priority": 2
            })
            # Return early - can't check mode-specific fields without source
            return missing
        
        # Priority 3: platform (REQUIRED if multiple platforms connected or none connected)
        # IMPORTANT: Check platform AFTER source is determined, but BEFORE metrics
        # This ensures we ask for platform selection when needed
        # Check if platform is missing - ask user to specify which platform
        platform = analytics_dict.get("platform")
        platform_list = platform if isinstance(platform, list) else [platform] if platform else []
        platform_list = [str(p).strip().lower() for p in platform_list if p]
        
        logger.info(f"🔍 Platform check: platform={platform}, platform_list={platform_list}, user_id={user_id}")
        
        # If no platform specified, check connected platforms
        if not platform_list and user_id:
            try:
                from agents.tools.Orion_Analytics_query import fetch_connected_platforms
                connected_platforms = fetch_connected_platforms(user_id)
                if len(connected_platforms) > 1:
                    # Multiple platforms - ask user to choose
                    missing.append({
                        "field": "platform",
                        "question": "Which platform would you like to analyze?",
                        "options": connected_platforms,
                        "priority": 3
                    })
                    return missing
                elif len(connected_platforms) == 1:
                    # Only one platform - auto-assign it
                    analytics_dict["platform"] = connected_platforms
                    platform_list = connected_platforms
                    logger.info(f"Auto-assigned single connected platform: {connected_platforms}")
                else:
                    # No platforms connected - ask user to specify
                    missing.append({
                        "field": "platform",
                        "question": "Which platform would you like to analyze?",
                        "options": ["instagram", "facebook", "youtube", "linkedin", "twitter", "pinterest"],
                        "priority": 3
                    })
                    return missing
            except Exception as e:
                logger.warning(f"Error checking connected platforms: {e}")
                # If we can't check, ask user to specify
                missing.append({
                    "field": "platform",
                    "question": "Which platform would you like to analyze?",
                    "options": ["instagram", "facebook", "youtube", "linkedin", "twitter", "pinterest"],
                    "priority": 3
                })
                return missing
        elif not platform_list:
            # No user_id available - ask user to specify platform
            missing.append({
                "field": "platform",
                "question": "Which platform would you like to analyze?",
                "options": ["instagram", "facebook", "youtube", "linkedin", "twitter", "pinterest"],
                "priority": 3
            })
            return missing
        
        # Priority 4: metrics/blog_metrics (conditional)
        # Only check if we have insight_type and source
        if insight_type == "improvement":
            # IMPROVEMENT MODE: metrics are REQUIRED
            if source == "social_media":
                # FIX 4: Check for None OR empty list
                metrics = analytics_dict.get("metrics")
                if not metrics or (isinstance(metrics, list) and len(metrics) == 0):
                    missing.append({
                        "field": "metrics",
                        "question": "What would you like to improve? Choose one or more metrics:",
                        "options": [
                            "reach", "impressions", "engagement", "likes", "comments", "shares",
                            "saves", "views", "profile_visits", "followers", "growth", "top_posts",
                            "all_posts", "average_watch_time", "avg_view_time", "watch_time"
                        ],
                        "priority": 3
                    })
            elif source == "blog":
                # FIX 4: Check for None OR empty list
                blog_metrics = analytics_dict.get("blog_metrics")
                if not blog_metrics or (isinstance(blog_metrics, list) and len(blog_metrics) == 0):
                    missing.append({
                        "field": "blog_metrics",
                        "question": "Which blog metrics would you like to improve?",
                        "options": [
                            "views", "read_time", "bounce_rate", "engagement",
                            "traffic_sources", "top_articles", "all_articles"
                        ],
                        "priority": 3
                    })
            # INSIGHT MODE: metrics are OPTIONAL (will use defaults)
            # Don't add to missing fields - we'll use defaults
        
        # Sort by priority
        missing.sort(key=lambda x: x.get("priority", 999))
        return missing
    
    def _generate_clarifying_question(self, missing_fields: List[Dict[str, Any]], intent_type: str) -> str:
        """Generate a clarifying question with options for missing fields"""
        if not missing_fields:
            return ""
        
        # Take the first missing field (highest priority)
        field_info = missing_fields[0]
        question = field_info["question"]
        
        # Add options if available
        if field_info.get("options"):
            options_text = ", ".join([f"**{opt}**" for opt in field_info["options"]])
            question += f"\n\nYou can pick from: {options_text} - or just tell me what you prefer!"
        
        return question
    
    def classify_intent(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Classify user query into intent and populate Pydantic payload"""
        query = state["current_query"]
        partial_payload = state.get("partial_payload")
        conversation_history = state.get("conversation_history", [])
        
        # Log the user query
        logger.info(f"Classifying intent for query: {query}")
        if partial_payload:
            logger.info(f"Merging with existing partial payload: {json.dumps(partial_payload, indent=2)}")
        
        # Build context from conversation history
        history_context = ""
        if conversation_history:
            recent_history = conversation_history[-5:]  # Last 5 messages
            history_context = "\n\nRecent conversation:\n"
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_context += f"{role}: {content}\n"
        
        # Include partial payload context if exists
        partial_context = ""
        if partial_payload:
            partial_context = f"\n\nPreviously collected information:\n{json.dumps(partial_payload, indent=2)}\n\nExtract any new information from the user's query and merge it with the existing data. Keep all previously collected non-null values."
        
        # Create the classification prompt
        classification_prompt = f"""You are an intent classifier for a business assistant chatbot.

Your job:
1. Read the user's natural language query
2. Classify it into the correct intent (one of: content_generation, analytics, leads_management, posting_manager, general_talks)
3. Extract ALL entities and information from the user's query - be thorough and extract everything mentioned
4. Produce a Pydantic-validated payload according to the provided schema
5. If the user query does not contain enough information, populate whatever fields you can and leave the rest as null
6. DO NOT hallucinate missing information
7. If information is missing and required later, mark the missing fields as null - the graph nodes will ask clarifying questions
8. Always output JSON only, following the exact structure of the Pydantic models
9. If there's existing partial payload data, merge the new information with it (keep existing non-null values, only update with new information from the current query)

Your output MUST strictly follow this root structure:
{{
  "intent": "...",
  "content": {{"type": "social_media" | "blog" | "email" | "whatsapp" | "ads", "social_media": {{"platform": "...", "content_type": "...", "idea": "..."}}, ...}} | null,
  "analytics": {{...}} | null,
  "leads": {{...}} | null,
  "posting": {{...}} | null,
  "general": {{...}} | null
}}

CRITICAL: ENTITY EXTRACTION FOR CONTENT GENERATION
When the user mentions content creation, you MUST extract ALL entities from their query:

1. PLATFORM EXTRACTION - Extract platform names from the query:
   - "instagram" → platform: ["instagram"]
   - "facebook" → platform: ["facebook"]
   - "youtube" → platform: ["youtube"]
   - "linkedin" → platform: ["linkedin"]
   - "twitter" → platform: ["twitter"]
   - "pinterest" → platform: ["pinterest"]
   - If multiple platforms mentioned, extract all: ["instagram", "facebook"]
   - If user says "instagram reel", extract platform: ["instagram"]

2. CONTENT_TYPE EXTRACTION - Extract content type from the query:
   - "reel" or "reels" → content_type: "reel"
   - "post" or "posts" → content_type: "post"
   - "video" or "videos" → content_type: "video"
   - "story" or "stories" → content_type: "story"
   - "carousel" or "carousels" → content_type: "carousel"
   - If user says "instagram reel", extract content_type: "reel"

3. IDEA/TOPIC EXTRACTION - Extract any topic, idea, or subject mentioned:
   - "product launch" → idea: "product launch"
   - "company update" → idea: "company update"
   - "tip about marketing" → idea: "tip about marketing"
   - Any descriptive text about what the content should be about

EXAMPLES OF CORRECT EXTRACTION:
- User: "i want to create an instagram reel"
  Output: {{
    "intent": "content_generation",
    "content": {{
      "type": "social_media",
      "social_media": {{
        "platform": ["instagram"],
        "content_type": "reel",
        "idea": null
      }}
    }},
    ...
  }}

- User: "create a facebook post about our new product"
  Output: {{
    "intent": "content_generation",
    "content": {{
      "type": "social_media",
      "social_media": {{
        "platform": ["facebook"],
        "content_type": "post",
        "idea": "our new product"
      }}
    }},
    ...
  }}

- User: "make a youtube video"
  Output: {{
    "intent": "content_generation",
    "content": {{
      "type": "social_media",
      "social_media": {{
        "platform": ["youtube"],
        "content_type": "video",
        "idea": null
      }}
    }},
    ...
  }}

IMPORTANT RULES FOR CONTENT GENERATION:
- If intent is "content_generation", the "content" object MUST include a "type" field
- The "type" field MUST be one of: "social_media", "blog", "email", "whatsapp", "ads"
- If the user says "post", "reel", "video", "story", "carousel" → infer type as "social_media"
- If the user says "blog" or "article", infer type as "blog"
- If the user says "email", infer type as "email"
- If the user says "whatsapp" or "message", infer type as "whatsapp"
- If the user says "ad" or "advertisement", infer type as "ads"
- ALWAYS extract platform and content_type when mentioned in the query
- NEVER create a "content" object without a "type" field
- For social_media type, ALWAYS create the "social_media" nested object with extracted fields

EMAIL-SPECIFIC RULES:
- For email type, use these EXACT field names in the "email" nested object:
  - "email_address" (NOT "recipient", "to", "email", etc.) - the recipient's email address
  - "content" (NOT "body", "message", "text", "subject", etc.) - what the email should be about
  - "attachments" (array of strings) - file paths or URLs for email attachments (extract if user mentions "attach", "attachment", "file", "document", etc.)
  - "task" (one of: "send", "save", "schedule") - what to do with the email
- If user mentions an email address, extract it as "email_address" in the "email" object
- If user describes what the email should be about (e.g., "product launch", "meeting invitation"), extract it as "content" in the "email" object
- If user mentions attachments (e.g., "attach the PDF", "with the document"), extract file references as "attachments" array
- Example: User says "send email to john@example.com about product launch"
  Output: {{"intent": "content_generation", "content": {{"type": "email", "email": {{"email_address": "john@example.com", "content": "product launch", "task": "send"}}}}}}
- Example: User says "email to jane@example.com with the invoice attached"
  Output: {{"intent": "content_generation", "content": {{"type": "email", "email": {{"email_address": "jane@example.com", "attachments": ["invoice"], "task": "send"}}}}}}

WHATSAPP-SPECIFIC RULES:
- For whatsapp type, use these EXACT field names in the "whatsapp" nested object:
  - "phone_number" (NOT "phone", "number", etc.) - recipient's phone number with country code
  - "text" (NOT "message", "content", "body", etc.) - the message text
  - "attachment" (string) - file path or URL for WhatsApp attachment (extract if user mentions "attach", "attachment", "file", "image", "video", etc.)
  - "task" (one of: "send", "schedule", "save") - what to do with the message
- If user mentions a phone number, extract it as "phone_number" in the "whatsapp" object
- If user mentions attachments (e.g., "send image", "with a video"), extract file reference as "attachment" string
- Example: User says "send WhatsApp to +919876543210 with the image"
  Output: {{"intent": "content_generation", "content": {{"type": "whatsapp", "whatsapp": {{"phone_number": "+919876543210", "attachment": "image", "task": "send"}}}}}}

BLOG-SPECIFIC RULES:
- For blog type, use these EXACT field names in the "blog" nested object:
  - "topic" - what the blog post should be about (e.g., "marketing tips", "product review")
  - "platform" (one of: "wordpress", "shopify", "wix", "html") - where to publish the blog
  - "length" (one of: "short", "medium", "long") - how long the blog post should be
  - "media" (one of: "generate", "upload") - whether to generate new media or upload existing media
  - "media_file" (string) - file path or URL if user mentions uploading a specific file
  - "task" (one of: "draft", "schedule", "save") - what to do with the blog post
- If user mentions a blog topic, extract it as "topic" in the "blog" object
- If user mentions a platform (wordpress, shopify, wix, html), extract it as "platform" in the "blog" object
- If user mentions length (short, medium, long), extract it as "length" in the "blog" object
- If user says "upload image", "use this photo", "attach file" → set media: "upload" and extract file reference as "media_file"
- If user says "generate image", "create visual", "make graphic" → set media: "generate"
- Example: User says "create a blog post about digital marketing for wordpress"
  Output: {{"intent": "content_generation", "content": {{"type": "blog", "blog": {{"topic": "digital marketing", "platform": "wordpress", "length": null, "task": null}}}}}}
- Example: User says "blog post with this image: /path/to/image.jpg"
  Output: {{"intent": "content_generation", "content": {{"type": "blog", "blog": {{"media": "upload", "media_file": "/path/to/image.jpg"}}}}}}
- When merging with existing partial payload, preserve all non-null blog fields and only update with new information

SOCIAL MEDIA MEDIA RULES:
- For social_media type, also extract media information if mentioned:
  - "media" (one of: "upload", "generate") - whether to upload existing media or generate new media
  - "media_file" (string) - file path or URL if user mentions uploading a specific file
- If user says "upload image", "use this photo", "attach file", OR JUST "upload" → set media: "upload" and extract file reference as "media_file" if provided
- If user says "generate image", "create visual", "make graphic", OR JUST "generate" → set media: "generate"
- CRITICAL: If the user responds with ONLY "generate" or ONLY "upload" (without other context), this is a direct answer to the media question - extract it as media: "generate" or media: "upload" respectively

SOCIAL MEDIA TASK AND DATE RULES:
- For social_media type, also extract task and date information if mentioned:
  - "task" (one of: "draft", "schedule", "edit", "delete") - what to do with the post after generation
  - "date" (ISO datetime string) - when to schedule the post (only needed if task is "schedule")
- If user says "draft", "save as draft", "save it" → set task: "draft"
- If user says "schedule", "schedule it", "schedule for later" → set task: "schedule"
- If user says "edit", "modify", "change" → set task: "edit"
- If user says "delete", "remove", "remove it" → set task: "delete"
- If user mentions a date/time for scheduling (e.g., "December 25, 2024 at 2:00 PM", "tomorrow at 10am"), extract it as "date" in ISO format
- CRITICAL: If the user responds with ONLY "draft", "schedule", "edit", or "delete" (without other context), this is a direct answer to the task question - extract it accordingly
- Example: User says "create an instagram post with this image: /path/to/image.jpg"
  Output: {{"intent": "content_generation", "content": {{"type": "social_media", "social_media": {{"platform": ["instagram"], "content_type": "post", "media": "upload", "media_file": "/path/to/image.jpg"}}}}}}
- Example: User says "generate" (as a response to media question)
  Output: {{"intent": "content_generation", "content": {{"type": "social_media", "social_media": {{"media": "generate"}}}}}}
- Example: User says "schedule it for tomorrow at 10am"
  Output: {{"intent": "content_generation", "content": {{"type": "social_media", "social_media": {{"task": "schedule", "date": "2024-12-26T10:00:00Z"}}}}}}
- Example: User says "edit" (as a response to task question)
  Output: {{"intent": "content_generation", "content": {{"type": "social_media", "social_media": {{"task": "edit"}}}}}}
- Example: User says "delete" (as a response to task question)
  Output: {{"intent": "content_generation", "content": {{"type": "social_media", "social_media": {{"task": "delete"}}}}}}
- When merging with existing partial payload, preserve all non-null social_media fields and only update with new information

General Rules:
- EXACT intent labels must be used: content_generation, analytics, leads_management, posting_manager, general_talks
- EXACT enum values must be used (e.g., "facebook", "instagram" for platforms; "post", "reel", "video", "story", "carousel" for content_type)
- Never output fields that are not in the Pydantic schema
- Never assume unknown fields
- If a query is conversational or does not match any domain, classify it under "general_talks"
- You must always return every top-level key, even if null
- If merging with existing data, preserve all non-null existing values and only add/update with new information from the current query
- BE THOROUGH: Extract every piece of information the user mentions - don't leave fields as null if they're clearly stated in the query

{partial_context}
{history_context}

User query: "{query}"

Return ONLY valid JSON matching the IntentPayload structure. No explanations, no markdown, no comments."""

        try:
            # Use structured output to get JSON
            response = self.llm.invoke([HumanMessage(content=classification_prompt)])
            
            # Log the raw LLM response
            logger.info(f"LLM raw response: {response.content}")
            
            # Parse the JSON response
            try:
                content = response.content.strip()
                
                # Remove markdown code blocks if present
                if content.startswith("```json"):
                    content = content[7:]  # Remove ```json
                elif content.startswith("```"):
                    content = content[3:]  # Remove ```
                
                if content.endswith("```"):
                    content = content[:-3]  # Remove closing ```
                
                content = content.strip()
                
                # Log the cleaned content before parsing
                logger.debug(f"LLM cleaned response: {content}")
                
                payload_dict = json.loads(content)
                
                # Merge with existing partial payload if it exists
                if partial_payload:
                    payload_dict = self._merge_payloads(partial_payload, payload_dict)
                    logger.info(f"Merged payload dict: {json.dumps(payload_dict, indent=2)}")
                
                # Log the parsed payload
                logger.info(f"Parsed payload dict: {json.dumps(payload_dict, indent=2)}")
                
                # Normalize and fix payload structure (but don't validate yet)
                payload_dict = self._normalize_payload(payload_dict)
                logger.info(f"Payload dict after normalization: {json.dumps(payload_dict, indent=2)}")
                
                # IMPORTANT: Ensure content is None if it's invalid (has type=None or missing type)
                # This prevents validation errors when creating minimal IntentPayload
                if payload_dict.get("content") and isinstance(payload_dict["content"], dict):
                    content_obj = payload_dict["content"]
                    content_type = content_obj.get("type")
                    if not content_type or content_type is None or content_type == "null" or content_type == "":
                        logger.warning(f"Content object has invalid type (type={content_type}), removing it from payload")
                        payload_dict["content"] = None
                
                # Store the merged payload as partial_payload for next iteration
                state["partial_payload"] = payload_dict
                
                # Create a minimal IntentPayload with just the intent for routing
                # We'll validate the full payload later when all required fields are collected
                intent_value = payload_dict.get("intent", "general_talks")
                
                # Create minimal payload for routing - only validate the intent
                # IMPORTANT: Set all payload fields to None to avoid validation
                # We only need the intent for routing
                try:
                    # Create IntentPayload with minimal data for routing
                    # Always set content to None to avoid validation
                    minimal_payload = {
                        "intent": intent_value,
                        "content": None,  # Always None - we'll validate later
                        "analytics": None,
                        "leads": None,
                        "posting": None,
                        "general": None
                    }
                    intent_payload = IntentPayload(**minimal_payload)
                    state["intent_payload"] = intent_payload
                    logger.info(f"Intent classified as: {intent_value} (payload stored in partial_payload, validation deferred)")
                except Exception as e:
                    logger.error(f"Failed to create minimal IntentPayload: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # Fallback to general_talks
                    state["intent_payload"] = IntentPayload(
                        intent="general_talks",
                        general=GeneralTalkPayload(message=query)
                    )
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM response: {e}")
                logger.error(f"Response content: {response.content}")
                # Fallback to general_talks
                state["intent_payload"] = IntentPayload(
                    intent="general_talks",
                    general=GeneralTalkPayload(message=query)
                )
            except Exception as e:
                logger.error(f"Error processing payload: {e}")
                logger.error(f"Payload dict: {json.dumps(payload_dict, indent=2) if 'payload_dict' in locals() else 'N/A'}")
                
                # Try to fix common issues and store as partial payload
                if 'payload_dict' in locals():
                    try:
                        # Try normalization again
                        fixed_payload = self._normalize_payload(payload_dict.copy())
                        state["partial_payload"] = fixed_payload
                        
                        # Create minimal IntentPayload for routing
                        intent_value = fixed_payload.get("intent", "general_talks")
                        minimal_payload = {
                            "intent": intent_value,
                            "content": None,
                            "analytics": None,
                            "leads": None,
                            "posting": None,
                            "general": None
                        }
                        intent_payload = IntentPayload(**minimal_payload)
                        state["intent_payload"] = intent_payload
                        logger.info(f"Fixed payload structure, intent: {intent_value} (validation deferred)")
                    except Exception as retry_error:
                        logger.error(f"Retry after normalization also failed: {retry_error}")
                        # Fallback to general_talks
                        state["intent_payload"] = IntentPayload(
                            intent="general_talks",
                            general=GeneralTalkPayload(message=query)
                        )
                else:
                    # Fallback to general_talks
                    state["intent_payload"] = IntentPayload(
                        intent="general_talks",
                        general=GeneralTalkPayload(message=query)
                    )
                
        except Exception as e:
            logger.error(f"Error in classify_intent: {e}")
            # Fallback to general_talks
            state["intent_payload"] = IntentPayload(
                intent="general_talks",
                general=GeneralTalkPayload(message=query)
            )
        
        return state
    
    def handle_content_generation(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Handle content generation intent"""
        try:
            from agents.tools.Leo_Content_Generation import execute_content_generation
            
            # Get the partial payload dictionary (not validated yet)
            partial_payload = state.get("partial_payload", {})
            content_dict = partial_payload.get("content")
            
            # Quick check: if user just said "generate" or "upload" and we're waiting for media, set it directly
            # Also check for "draft" or "schedule" for task field
            user_query = state.get("current_query", "").strip()
            user_query_lower = user_query.lower()
            if content_dict and content_dict.get("type") == "social_media":
                social_media_dict = content_dict.get("social_media", {})
                
                # Check if user sent "upload {url}" format (from file upload)
                if user_query_lower.startswith("upload ") and len(user_query) > 7:
                    # Extract URL from "upload {url}"
                    file_url = user_query[7:].strip()  # Remove "upload " prefix
                    if file_url and (file_url.startswith("http://") or file_url.startswith("https://")):
                        if "social_media" not in content_dict:
                            content_dict["social_media"] = {}
                        content_dict["social_media"]["media"] = "upload"
                        content_dict["social_media"]["media_file"] = file_url
                        partial_payload["content"] = content_dict
                        state["partial_payload"] = partial_payload
                        logger.info(f"Directly set media to 'upload' with file URL: {file_url}")
                elif not social_media_dict.get("media"):
                    if user_query_lower == "generate":
                        if "social_media" not in content_dict:
                            content_dict["social_media"] = {}
                        content_dict["social_media"]["media"] = "generate"
                        partial_payload["content"] = content_dict
                        state["partial_payload"] = partial_payload
                        logger.info("Directly set media to 'generate' from user query")
                    elif user_query_lower == "upload":
                        if "social_media" not in content_dict:
                            content_dict["social_media"] = {}
                        content_dict["social_media"]["media"] = "upload"
                        partial_payload["content"] = content_dict
                        state["partial_payload"] = partial_payload
                        logger.info("Directly set media to 'upload' from user query")
            
            # Re-get content_dict after potential update
            content_dict = partial_payload.get("content")
            
            if not content_dict:
                state["response"] = "I'd love to help you create some content! What are you thinking - are you looking to create something for social media, write a blog post, send an email, create a WhatsApp message, or maybe work on some ads?"
                state["needs_clarification"] = True
                return state
            
            # Check if type is set
            content_type = content_dict.get("type")
            if not content_type:
                state["response"] = "Sounds good! Just to make sure I create exactly what you need - are you thinking social media content, a blog post, an email, a WhatsApp message, or maybe some ads?"
                state["needs_clarification"] = True
                return state
            
            # Check for missing required fields based on content type
            # Handle social_media type
            if content_type == "social_media":
                social_media_dict = content_dict.get("social_media", {})
                
                # Check for missing fields using dictionary
                missing_fields = []
                if not social_media_dict.get("platform"):
                    missing_fields.append({
                        "field": "platform",
                        "question": "Great! Which social media platform are you thinking of? Are you looking to post on Facebook, Instagram, YouTube, LinkedIn, Twitter, or Pinterest?",
                        "options": ["facebook", "instagram", "youtube", "linkedin", "twitter", "pinterest"],
                        "priority": 1
                    })
                
                if not social_media_dict.get("content_type"):
                    missing_fields.append({
                        "field": "content_type",
                        "question": "What kind of content are you planning? Are you thinking of a regular post, a reel, a video, a story, or maybe a carousel?",
                        "options": ["post", "reel", "video", "story", "carousel"],
                        "priority": 2
                    })
                
                if not social_media_dict.get("idea"):
                    missing_fields.append({
                        "field": "idea",
                        "question": "What would you like to share in this social media post?",
                        "options": None,
                        "priority": 3
                    })
                
                # Check for media field (lower priority - ask after core fields are filled)
                if not social_media_dict.get("media"):
                    missing_fields.append({
                        "field": "media",
                        "question": "Great! For the visuals, would you like me to generate an image for this post, or do you have a file you'd like to upload?",
                        "options": ["generate", "upload"],
                        "priority": 4
                    })
                # If media is "upload" but media_file is missing, ask for the file
                elif social_media_dict.get("media") == "upload" and not social_media_dict.get("media_file"):
                    missing_fields.append({
                        "field": "media_file",
                        "question": "Perfect! You mentioned uploading a file. Could you share the file path or URL for the image/video you'd like to use?",
                        "options": None,
                        "priority": 4
                    })
                
                # Sort by priority
                missing_fields.sort(key=lambda x: x.get("priority", 999))
                
                logger.info(f"Missing fields for social_media: {missing_fields}")
                if missing_fields:
                    question = self._generate_clarifying_question(missing_fields, "social_media")
                    state["response"] = question
                    state["needs_clarification"] = True
                    # Store options for frontend rendering
                    field_info = missing_fields[0]
                    state["options"] = field_info.get("options")
                    logger.info(f"Generated clarifying question: {question}")
                    logger.info(f"Options for frontend: {state['options']}")
                    return state
            
            # Handle email type
            elif content_type == "email":
                email_dict = content_dict.get("email", {})
                
                # Check for missing fields using dictionary
                # Also check for "recipient" as an alias for "email_address"
                missing_fields = []
                email_address = email_dict.get("email_address") or email_dict.get("recipient")
                if not email_address:
                    missing_fields.append({
                        "field": "email_address",
                        "question": "Sure! Who should I send this email to? What's their email address?",
                        "options": None,
                        "priority": 1
                    })
                
                # Check for content field, also check common aliases
                email_content = email_dict.get("content") or email_dict.get("body") or email_dict.get("message") or email_dict.get("text") or email_dict.get("subject") or email_dict.get("topic") or email_dict.get("about")
                if not email_content:
                    missing_fields.append({
                        "field": "content",
                        "question": "What's this email going to be about? Are you announcing a product, inviting them to a meeting, sending a newsletter, or something else?",
                        "options": None,
                        "priority": 2
                    })
                
                if not email_dict.get("task"):
                    missing_fields.append({
                        "field": "task",
                        "question": "Got it! What would you like me to do with this email? Should I send it right away, save it as a draft, or schedule it for later?",
                        "options": ["send", "save", "schedule"],
                        "priority": 3
                    })
                
                # Sort by priority
                missing_fields.sort(key=lambda x: x.get("priority", 999))
                
                logger.info(f"Missing fields for email: {missing_fields}")
                if missing_fields:
                    question = self._generate_clarifying_question(missing_fields, "email")
                    state["response"] = question
                    state["needs_clarification"] = True
                    # Store options for frontend rendering
                    field_info = missing_fields[0]
                    state["options"] = field_info.get("options")
                    logger.info(f"Generated clarifying question: {question}")
                    logger.info(f"Options for frontend: {state['options']}")
                    return state
            
            # Handle blog type
            elif content_type == "blog":
                blog_dict = content_dict.get("blog", {})
                
                # Check for missing fields using dictionary
                missing_fields = []
                if not blog_dict.get("topic"):
                    missing_fields.append({
                        "field": "topic",
                        "question": "Awesome! What topic are you thinking of writing about? For example, are you sharing marketing tips, doing a product review, covering industry news, or something else?",
                        "options": None,
                        "priority": 1
                    })
                
                if not blog_dict.get("platform"):
                    missing_fields.append({
                        "field": "platform",
                        "question": "Perfect! Where are you planning to publish this? Are you using WordPress, Shopify, Wix, or maybe a custom HTML site?",
                        "options": ["wordpress", "shopify", "wix", "html"],
                        "priority": 2
                    })
                
                if not blog_dict.get("length"):
                    missing_fields.append({
                        "field": "length",
                        "question": "How long are you thinking? Are you going for a quick short read, a medium-length article, or a longer deep dive?",
                        "options": ["short", "medium", "long"],
                        "priority": 3
                    })
                
                if not blog_dict.get("task"):
                    missing_fields.append({
                        "field": "task",
                        "question": "Great! What would you like me to do with this blog post? Should I create it as a draft for you to review, schedule it to publish later, or just save it for now?",
                        "options": ["draft", "schedule", "save"],
                        "priority": 4
                    })
                
                # Sort by priority
                missing_fields.sort(key=lambda x: x.get("priority", 999))
                
                logger.info(f"Missing fields for blog: {missing_fields}")
                if missing_fields:
                    question = self._generate_clarifying_question(missing_fields, "blog")
                    state["response"] = question
                    state["needs_clarification"] = True
                    # Store options for frontend rendering
                    field_info = missing_fields[0]
                    state["options"] = field_info.get("options")
                    logger.info(f"Generated clarifying question: {question}")
                    logger.info(f"Options for frontend: {state['options']}")
                    return state
            
            # If all required fields are present, validate and execute
            # Now we validate the complete payload
            try:
                # Normalize one more time to ensure structure is correct
                normalized_payload = self._normalize_payload(partial_payload.copy())
                logger.info(f"Normalized payload before validation: {json.dumps(normalized_payload, indent=2, default=str)}")
                
                intent_payload = IntentPayload(**normalized_payload)
                payload = intent_payload.content
                
                if not payload:
                    logger.error("Payload is None after validation")
                    state["response"] = "I encountered an error: Content payload is missing. Please try again."
                    state["needs_clarification"] = True
                    return state
                
                logger.info("All required fields present, validating and executing payload")
                result = execute_content_generation(payload, state["user_id"])
            except Exception as validation_error:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Validation error when all fields should be present: {validation_error}")
                logger.error(f"Error traceback: {error_trace}")
                logger.error(f"Partial payload that failed: {json.dumps(partial_payload, indent=2, default=str)}")
                state["response"] = f"I encountered an error validating your request: {str(validation_error)}. Please try again or provide the information in a different way."
                state["needs_clarification"] = True  # Keep asking for clarification
                return state
            
            if result.get("clarifying_question"):
                state["response"] = result["clarifying_question"]
                state["needs_clarification"] = True
            elif result.get("success") and result.get("data"):
                # Store the structured content data in state for frontend
                data = result["data"]
                
                # Ensure images is always a list
                if "images" in data:
                    if not isinstance(data["images"], list):
                        data["images"] = [data["images"]] if data["images"] else []
                    # Filter out any None or empty values
                    data["images"] = [img for img in data["images"] if img and isinstance(img, str) and len(img) > 0]
                
                logger.info(f"📥 Received content generation result from Leo:")
                logger.info(f"  - Data keys: {list(data.keys())}")
                logger.info(f"  - Images: {data.get('images')}")
                logger.info(f"  - Images type: {type(data.get('images'))}")
                logger.info(f"  - Images length: {len(data.get('images', []))}")
                if data.get('images'):
                    for idx, img_url in enumerate(data['images']):
                        logger.info(f"    Image {idx + 1}: {img_url}")
                
                # Get saved_content_id and updated payload from the result
                saved_content_id = data.get("saved_content_id")
                updated_payload = result.get("payload")  # Full payload with content field set
                
                # Store in state
                state["content_data"] = data
                state["response"] = self._format_content_response(data)
                
                # Update partial payload with the full payload returned from Leo (includes content field)
                partial_payload = state.get("partial_payload", {})
                if updated_payload:
                    # Merge the updated payload from Leo into partial_payload
                    # The updated_payload should have the content field set to saved_content_id
                    if "content" not in partial_payload:
                        partial_payload["content"] = {}
                    if "social_media" not in partial_payload.get("content", {}):
                        partial_payload["content"]["social_media"] = {}
                    
                    # Merge the updated payload fields into partial_payload
                    for key, value in updated_payload.items():
                        if value is not None:  # Only update with non-null values
                            partial_payload["content"]["social_media"][key] = value
                    
                    logger.info(f"📝 Merged updated payload from Leo into partial_payload")
                    logger.info(f"   Payload content field: {partial_payload.get('content', {}).get('social_media', {}).get('content')}")
                elif saved_content_id:
                    # Fallback: if payload not returned, manually set content field
                    if "content" not in partial_payload:
                        partial_payload["content"] = {}
                    if "social_media" not in partial_payload.get("content", {}):
                        partial_payload["content"]["social_media"] = {}
                    partial_payload["content"]["social_media"]["content"] = saved_content_id
                    logger.info(f"📝 Fallback: Stored saved_content_id in payload.content.social_media.content: {saved_content_id}")
                
                # Content generation complete - task/date will be handled by posting manager
                # All fields complete, clear partial payload
                state["needs_clarification"] = False
                state["partial_payload"] = None
                
                logger.info(f"✅ Content data stored in state with {len(data.get('images', []))} image(s)")
            elif result.get("error"):
                state["response"] = f"I encountered an error: {result['error']}"
                state["needs_clarification"] = False
            else:
                state["response"] = "I've processed your content generation request."
                state["needs_clarification"] = False
                state["partial_payload"] = None
                
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Error in handle_content_generation: {e}")
            logger.error(f"Error traceback: {error_trace}")
            state["response"] = f"I encountered an error while processing your content generation request: {str(e)}. Please try again."
            state["needs_clarification"] = True  # Keep asking for clarification instead of giving up
        
        return state
    
    def handle_analytics(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """
        Handle analytics intent - COLLECTOR ONLY.
        
        FIX 1: Correct order - merge FIRST, then normalize, then check missing fields.
        FIX 2: Merge logic - new non-null values override old ones, empty lists not valid.
        FIX 3: Platform implies source - if platform provided, auto-assign source.
        FIX 4: Empty list handling - empty arrays count as missing.
        FIX 5: Direct answer handling - detect user answers without LLM.
        FIX 6: needs_clarification reset - reset when fields provided.
        FIX 7: Comprehensive logging.
        
        Emily's responsibilities:
        1. Extract analytics fields from partial_payload (from classify_intent)
        2. Detect direct user answers (fallback if LLM fails)
        3. Merge new data into partial_payload
        4. Normalize analytics payload (handle LLM drift, platform→source inference)
        5. Detect missing REQUIRED fields
        6. Ask clarifying questions if fields missing
        7. Validate into AnalyticsPayload
        8. Pass clean payload to Orion
        
        Emily does NOT:
        - Apply default metrics
        - Infer platforms (handled by Orion)
        - Execute analytics logic
        - Format responses
        - Handle DB calls
        
        All business logic is handled by Orion_Analytics_query.py
        """
        try:
            from agents.tools.Orion_Analytics_query import execute_analytics_query
            
            # Get the partial payload dictionary (not validated yet)
            partial_payload = state.get("partial_payload", {})
            user_query = state.get("current_query", "").strip()
            needs_clarification = state.get("needs_clarification", False)
            
            # Ensure analytics dict exists in partial_payload
            if "analytics" not in partial_payload:
                partial_payload["analytics"] = {}
            
            analytics_dict = partial_payload.get("analytics", {})
            
            # FIX 1 & FIX 5: STEP 1 - Extract and merge user answers FIRST (before normalization)
            # This ensures user input is captured even if LLM extraction fails
            # CRITICAL FIX: Run direct answer detection on ALL queries, not just when needs_clarification is True
            # This allows platform detection from first query like "i want analytics of instagram"
            if user_query:
                user_query_lower = user_query.strip().lower()
                
                # Direct answer detection for insight_type
                if user_query_lower in ["insight", "improvement"]:
                    existing_insight_type = analytics_dict.get("insight_type")
                    if not existing_insight_type or existing_insight_type not in ["insight", "improvement"]:
                        analytics_dict["insight_type"] = user_query_lower
                        logger.info(f"FIX 5: Direct answer detected for insight_type: {user_query_lower}")
                
                # Direct answer detection for source
                elif user_query_lower in ["social_media", "social", "blog", "blogs"]:
                    existing_source = analytics_dict.get("source")
                    if not existing_source or existing_source not in ["social_media", "blog"]:
                        source_value = "social_media" if user_query_lower in ["social_media", "social"] else "blog"
                        analytics_dict["source"] = source_value
                        logger.info(f"FIX 5: Direct answer detected for source: {source_value}")
                
                # Direct answer detection for platforms (FIX 3: platform implies source)
                # CRITICAL FIX: Check for platform names in the query using word-boundary matching
                # This handles cases like "analytics of instagram" or "instagram analytics"
                social_media_platforms = ["instagram", "facebook", "twitter", "youtube", "linkedin", "tiktok", "snapchat", "pinterest"]
                blog_platforms = ["wordpress", "medium", "substack", "blogger"]
                
                platform_found = None
                
                # First check if query is exactly a platform name
                if user_query_lower in social_media_platforms:
                    platform_found = user_query_lower
                elif user_query_lower in blog_platforms:
                    platform_found = user_query_lower
                else:
                    # Check if query contains a platform name (word-boundary match)
                    # This handles "analytics of instagram", "instagram analytics", etc.
                    for platform in social_media_platforms:
                        pattern = r'\b' + re.escape(platform) + r'\b'
                        if re.search(pattern, user_query_lower):
                            platform_found = platform
                            break
                    
                    if not platform_found:
                        for platform in blog_platforms:
                            pattern = r'\b' + re.escape(platform) + r'\b'
                            if re.search(pattern, user_query_lower):
                                platform_found = platform
                                break
                
                if platform_found:
                    # Update platform list
                    existing_platforms = analytics_dict.get("platform", [])
                    if not existing_platforms or not isinstance(existing_platforms, list):
                        existing_platforms = []
                    if platform_found not in existing_platforms:
                        existing_platforms.append(platform_found)
                        analytics_dict["platform"] = existing_platforms
                        logger.info(f"FIX 5: Direct answer detected for platform: {platform_found}")
                    
                    # FIX 3: Platform implies source - auto-assign source based on platform
                    if platform_found in social_media_platforms:
                        if not analytics_dict.get("source") or analytics_dict.get("source") not in ["social_media", "blog"]:
                            analytics_dict["source"] = "social_media"
                            logger.info(f"FIX 3: Platform '{platform_found}' implies source='social_media'")
                    elif platform_found in blog_platforms:
                        if not analytics_dict.get("source") or analytics_dict.get("source") not in ["social_media", "blog"]:
                            analytics_dict["source"] = "blog"
                            logger.info(f"FIX 3: Platform '{platform_found}' implies source='blog'")
                
                # Direct answer detection for metrics (only if not already handled above)
                if not platform_found and user_query_lower not in ["insight", "improvement", "social_media", "social", "blog", "blogs"]:
                    # BUG 2 FIX: Use word-boundary matching instead of substring matching to avoid false positives
                    # Example: "reach my goals" should NOT match "reach" metric
                    metric_keywords = ["reach", "impressions", "engagement", "likes", "comments", "shares", "saves", "views", "followers", "growth", "top_posts", "all_posts", "watch_time", "avg_view_time"]
                    
                    # Create word-boundary regex pattern for each metric
                    metrics_list = []
                    for keyword in metric_keywords:
                        # Use word boundaries to match whole words only
                        # \b matches word boundaries (start/end of string or non-word characters)
                        pattern = r'\b' + re.escape(keyword) + r'\b'
                        if re.search(pattern, user_query_lower):
                            metrics_list.append(keyword)
                    
                    if metrics_list:
                        existing_metrics = analytics_dict.get("metrics", [])
                        if not existing_metrics or not isinstance(existing_metrics, list) or len(existing_metrics) == 0:
                            analytics_dict["metrics"] = list(set(metrics_list))  # Remove duplicates
                            logger.info(f"FIX 5: Direct answer detected for metrics (word-boundary match): {metrics_list}")
            
            # FIX 1: STEP 2 - Normalize analytics payload (after merging user answers)
            # This handles LLM drift and applies platform→source inference
            normalized_analytics = self._normalize_analytics_payload(analytics_dict, user_query)
            
            # FIX 2: Merge normalized fields - new non-null values override old ones
            # Empty lists do NOT count as valid values
            for key, value in normalized_analytics.items():
                if value is not None:
                    # FIX 2: For lists, empty list is not valid - only merge non-empty lists
                    if isinstance(value, list):
                        if len(value) == 0:
                            continue  # Skip empty lists
                    
                    # FIX 2: New non-null values always override old ones
                    # BUT: Don't overwrite valid existing values with None or empty values
                    existing_value = analytics_dict.get(key)
                    
                    # Special handling: preserve valid existing values only if new value is also valid
                    if key == "insight_type":
                        if value in ["insight", "improvement"]:
                            analytics_dict[key] = value
                    elif key == "source":
                        # CRITICAL FIX: Always update source if value is valid, even if existing value exists
                        # This ensures user selections (like clicking "social_media" button) are always applied
                        if value in ["social_media", "blog"]:
                            analytics_dict[key] = value
                            logger.info(f"Source updated to: {value}")
                    elif key in ["platform", "metrics", "blog_metrics"]:
                        # For lists, only overwrite if new value is non-empty
                        if isinstance(value, list) and len(value) > 0:
                            analytics_dict[key] = value
                        # If existing value is valid and new value is empty, preserve existing
                        elif existing_value and isinstance(existing_value, list) and len(existing_value) > 0:
                            # Keep existing value, don't overwrite with empty
                            pass
                    elif key == "date_range":
                        # Always update date_range if provided (user might want to change it)
                        if isinstance(value, str) and value.strip():
                            analytics_dict[key] = value.strip()
                    else:
                        # For other fields, update if value is valid
                        analytics_dict[key] = value
            
            # Remove old fields that were normalized
            analytics_dict.pop("type", None)
            analytics_dict.pop("analysis_type", None)
            analytics_dict.pop("mode", None)
            analytics_dict.pop("analytics_type", None)
            analytics_dict.pop("insight", None)
            analytics_dict.pop("preference", None)
            analytics_dict.pop("metric", None)
            analytics_dict.pop("metric_type", None)
            analytics_dict.pop("blog_metric", None)
            
            # CRITICAL FIX: Ensure analytics_dict is stored back to partial_payload BEFORE checking missing fields
            # This ensures all direct answer detections and normalizations are persisted
            partial_payload["analytics"] = analytics_dict
            
            # FIX 7: Log post-normalization state
            logger.info(f"Post-normalization analytics payload: {json.dumps(analytics_dict, indent=2, default=str)}")
            logger.info(f"Source after normalization: {analytics_dict.get('source')}, Platform: {analytics_dict.get('platform')}")
            
            # FIX 1: STEP 3 - Check missing fields AFTER normalization
            user_id = state.get("user_id")
            missing_fields = self._get_missing_fields_for_analytics(analytics_dict, user_id)
            
            # FIX 7: Log missing fields
            logger.info(f"Missing fields after normalization: {missing_fields}")
            
            # FIX 6: Reset needs_clarification if fields were provided
            previous_missing_count = len(state.get("_previous_missing_fields", []))
            current_missing_count = len(missing_fields)
            
            if needs_clarification:
                if current_missing_count == 0:
                    # All fields provided
                    state["needs_clarification"] = False
                    logger.info("FIX 6: All required fields provided, resetting needs_clarification")
                elif current_missing_count < previous_missing_count:
                    # Some fields provided, progress made
                    logger.info(f"FIX 6: Progress made - missing fields reduced from {previous_missing_count} to {current_missing_count}")
            
            # Store current missing count for next iteration
            state["_previous_missing_fields"] = missing_fields
            
            if missing_fields:
                # FIX 6: Set needs_clarification if we're asking a question
                state["needs_clarification"] = True
                
                # Ask clarifying question
                question = self._generate_clarifying_question(missing_fields, "analytics")
                state["response"] = question
                # Store options for frontend rendering
                field_info = missing_fields[0]
                state["options"] = field_info.get("options")
                # IMPORTANT: Store partial_payload back in state so cache can save it
                state["partial_payload"] = partial_payload
                logger.info(f"Generated clarifying question: {question}")
                logger.info(f"Options for frontend: {state['options']}")
                logger.info(f"Stored partial_payload in state for caching: {json.dumps(partial_payload, indent=2, default=str)}")
                return state
            
            # 4. VALIDATE: All required fields present, validate into AnalyticsPayload
            try:
                # ERROR 1 FIX: Explicitly validate AnalyticsPayload before sending to Orion
                # AnalyticsPayload requires: insight_type and source (both non-optional)
                insight_type = analytics_dict.get("insight_type")
                source = analytics_dict.get("source")
                
                if not insight_type or insight_type not in ["insight", "improvement"]:
                    logger.error(f"insight_type missing or invalid after normalization: {insight_type}")
                    state["response"] = "I encountered an error: insight_type is missing or invalid. Please try again."
                    state["needs_clarification"] = True
                    state["partial_payload"] = partial_payload
                    return state
                
                if not source or source not in ["social_media", "blog"]:
                    logger.error(f"source missing or invalid after normalization: {source}")
                    state["response"] = "I encountered an error: source is missing or invalid. Please try again."
                    state["needs_clarification"] = True
                    state["partial_payload"] = partial_payload
                    return state
                
                # Normalize one more time to ensure structure is correct
                normalized_payload = self._normalize_payload(partial_payload.copy())
                logger.info(f"Normalized payload before validation: {json.dumps(normalized_payload, indent=2, default=str)}")
                
                # Validate into IntentPayload first
                intent_payload = IntentPayload(**normalized_payload)
                payload = intent_payload.analytics
                
                if not payload:
                    logger.error("Analytics payload is None after validation")
                    state["response"] = "I encountered an error: Analytics payload is missing. Please try again."
                    state["needs_clarification"] = True
                    state["partial_payload"] = partial_payload
                    return state
                
                # ERROR 1 FIX: Explicitly validate AnalyticsPayload object
                # The payload from IntentPayload should already be validated, but we ensure it's correct
                # AnalyticsPayload is already imported at module level, payload is already validated
                if not payload.insight_type or payload.insight_type not in ["insight", "improvement"]:
                    logger.error(f"Payload missing or invalid insight_type: {payload.insight_type}")
                    state["response"] = "I encountered an error: Required analytics fields are missing. Please try again."
                    state["needs_clarification"] = True
                    state["partial_payload"] = partial_payload
                    return state
                
                if not payload.source or payload.source not in ["social_media", "blog"]:
                    logger.error(f"Payload missing or invalid source: {payload.source}")
                    state["response"] = "I encountered an error: Required analytics fields are missing. Please try again."
                    state["needs_clarification"] = True
                    state["partial_payload"] = partial_payload
                    return state
                
                logger.info(f"✅ Validated AnalyticsPayload: insight_type={payload.insight_type}, source={payload.source}, platform={payload.platform}, metrics={payload.metrics}")
                
                # 5. EXECUTE: Pass clean AnalyticsPayload to Orion (Orion handles all business logic)
                logger.info("All required fields present, passing validated AnalyticsPayload to Orion for execution")
                result = execute_analytics_query(payload, state["user_id"])
            except Exception as validation_error:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Validation error when all fields should be present: {validation_error}")
                logger.error(f"Error traceback: {error_trace}")
                logger.error(f"Partial payload that failed: {json.dumps(partial_payload, indent=2, default=str)}")
                state["response"] = f"I encountered an error validating your request: {str(validation_error)}. Please try again or provide the information in a different way."
                state["needs_clarification"] = True  # Keep asking for clarification
                return state
            
            # 6. HANDLE RESPONSE: Pass through Orion's response (Orion handles all formatting)
            # ERROR 7 FIX: Properly handle Orion's clarifying_question structure
            if result.get("clarifying_question"):
                # Orion needs more info (e.g., platform selection, metrics)
                state["response"] = result["clarifying_question"]
                state["needs_clarification"] = True
                if "options" in result:
                    state["options"] = result["options"]
                # Keep partial_payload so user can continue the conversation
                state["partial_payload"] = partial_payload
                logger.info(f"Orion requested clarification: {result['clarifying_question']}")
                return state
            elif result.get("success") and result.get("data"):
                # Orion provides formatted message in data["message"]
                response_message = result["data"].get("message")
                if not response_message:
                    response_message = "Analytics data retrieved successfully."
                state["response"] = response_message
                state["needs_clarification"] = False
                state["partial_payload"] = None  # Clear partial payload on success
            elif result.get("error"):
                state["response"] = f"I encountered an error: {result['error']}"
                state["needs_clarification"] = False
            elif result.get("message"):
                # Handle messages from Orion (e.g., "No analytics data found")
                state["response"] = result["message"]
                state["needs_clarification"] = False
            else:
                state["response"] = "I've processed your analytics query."
                state["needs_clarification"] = False
                state["partial_payload"] = None
                
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Error in handle_analytics: {e}")
            logger.error(f"Error traceback: {error_trace}")
            state["response"] = f"I encountered an error while processing your analytics query: {str(e)}. Please try again."
            state["needs_clarification"] = True  # Keep asking for clarification instead of giving up
        
        return state
    
    def handle_leads_management(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Handle leads management intent"""
        try:
            from agents.tools.Chase_Leads_manager import execute_leads_operation
            
            payload = state["intent_payload"].leads
            if not payload:
                state["response"] = "I need more information about what you'd like to do with leads. Please specify the action."
                return state
            
            result = execute_leads_operation(payload, state["user_id"])
            
            if result.get("clarifying_question"):
                state["response"] = result["clarifying_question"]
            elif result.get("success") and result.get("data"):
                state["response"] = self._format_leads_response(result["data"])
            elif result.get("error"):
                state["response"] = f"I encountered an error: {result['error']}"
            else:
                state["response"] = "I've processed your leads management request."
                
        except Exception as e:
            logger.error(f"Error in handle_leads_management: {e}")
            state["response"] = "I encountered an error while processing your leads request. Please try again."
        
        return state
    
    def handle_posting_manager(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Handle posting manager intent"""
        try:
            from agents.tools.Emily_post_manager import execute_posting_operation
            
            payload = state["intent_payload"].posting
            if not payload:
                state["response"] = "I need more information about what you'd like to do with your posts. Please specify the action."
                return state
            
            result = execute_posting_operation(payload, state["user_id"])
            
            if result.get("clarifying_question"):
                state["response"] = result["clarifying_question"]
            elif result.get("success") and result.get("data"):
                state["response"] = self._format_posting_response(result["data"])
            elif result.get("error"):
                state["response"] = f"I encountered an error: {result['error']}"
            else:
                state["response"] = "I've processed your posting request."
                
        except Exception as e:
            logger.error(f"Error in handle_posting_manager: {e}")
            state["response"] = "I encountered an error while processing your posting request. Please try again."
        
        return state
    
    def handle_general_talks(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Handle general conversational intent"""
        try:
            from agents.tools.general_chat_tool import execute_general_chat
            
            payload = state["intent_payload"].general
            if not payload:
                payload = GeneralTalkPayload(message=state["current_query"])
            
            result = execute_general_chat(payload, state["user_id"])
            
            if result.get("success") and result.get("data"):
                state["response"] = result["data"]
            elif result.get("error"):
                state["response"] = f"I encountered an error: {result['error']}"
            else:
                state["response"] = "I'm here to help! How can I assist you today?"
                
        except Exception as e:
            logger.error(f"Error in handle_general_talks: {e}")
            state["response"] = "I'm here to help! How can I assist you today?"
        
        return state
    
    def generate_final_response(self, state: IntentBasedChatbotState) -> IntentBasedChatbotState:
        """Final response formatting node"""
        # Response is already set in handler nodes
        # This node can be used for additional formatting if needed
        return state
    
    def _format_content_response(self, data: Any) -> str:
        """Format content generation response with structured content"""
        if isinstance(data, dict):
            # Check if this is structured content (title, content, hashtags, images)
            # If it has structured content data, return a simple message (card will be displayed separately)
            if "title" in data and "content" in data:
                # Return simple message - the card will be displayed from content_data
                return "Here is the post you requested"
            elif "message" in data:
                return data["message"]
            elif "content" in data:
                return data["content"]
        return str(data)
    
    
    def _format_leads_response(self, data: Any) -> str:
        """Format leads management response"""
        if isinstance(data, dict):
            if "message" in data:
                return data["message"]
            elif "summary" in data:
                return data["summary"]
        return str(data)
    
    def _format_posting_response(self, data: Any) -> str:
        """Format posting manager response"""
        if isinstance(data, dict):
            if "message" in data:
                return data["message"]
            elif "summary" in data:
                return data["summary"]
        return str(data)
    
    def chat(self, user_id: str, query: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> str:
        """Main chat interface (deprecated - use get_intent_based_response instead)"""
        try:
            # This method is kept for backward compatibility
            # The actual implementation is now in get_intent_based_response
            initial_state: IntentBasedChatbotState = {
                "user_id": user_id,
                "current_query": query,
                "conversation_history": conversation_history or [],
                "intent_payload": None,
                "partial_payload": None,
                "response": None,
                "context": {},
                "needs_clarification": False,
                "options": None,
                "content_data": None
            }
            
            # Run the graph
            result = self.graph.invoke(initial_state)
            
            return result.get("response", "I apologize, but I couldn't process your request.")
            
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            return "I apologize, but I encountered an error while processing your request."

# Global instance
_intent_based_chatbot = None

# In-memory cache for partial payloads (keyed by user_id)
# In production, this could be stored in Redis or database
_partial_payload_cache: Dict[str, Dict[str, Any]] = {}

def clear_partial_payload_cache(user_id: str) -> None:
    """Clear the partial payload cache for a specific user"""
    _partial_payload_cache.pop(user_id, None)
    logger.info(f"Cleared partial payload cache for user {user_id}")

def get_intent_based_chatbot() -> IntentBasedChatbot:
    """Get or create the intent-based chatbot instance"""
    global _intent_based_chatbot
    if _intent_based_chatbot is None:
        _intent_based_chatbot = IntentBasedChatbot()
    return _intent_based_chatbot

def get_intent_based_response(user_id: str, message: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Get response from intent-based chatbot"""
    chatbot = get_intent_based_chatbot()
    
    # Retrieve partial payload from cache if exists
    partial_payload = _partial_payload_cache.get(user_id)
    
    # Create state with partial payload
    initial_state: IntentBasedChatbotState = {
        "user_id": user_id,
        "current_query": message,
        "conversation_history": conversation_history or [],
        "intent_payload": None,
        "partial_payload": partial_payload,
        "response": None,
        "context": {},
        "needs_clarification": False,
        "options": None,
        "content_data": None
    }
    
    # Run the graph
    result = chatbot.graph.invoke(initial_state)
    
    # Update cache with new partial payload if clarification is needed
    if result.get("needs_clarification") and result.get("partial_payload"):
        _partial_payload_cache[user_id] = result["partial_payload"]
    elif not result.get("needs_clarification"):
        # Clear cache when request is complete
        _partial_payload_cache.pop(user_id, None)
    
    return {
        "response": result.get("response", "I apologize, but I couldn't process your request."),
        "options": result.get("options"),
        "content_data": result.get("content_data")  # Include structured content data (title, content, hashtags, images)
    }

def get_intent_based_response_stream(user_id: str, message: str, conversation_history: Optional[List[Dict[str, str]]] = None):
    """Stream response from intent-based chatbot"""
    chatbot = get_intent_based_chatbot()
    
    # Retrieve partial payload from cache if exists
    partial_payload = _partial_payload_cache.get(user_id)
    
    # Create state with partial payload
    initial_state: IntentBasedChatbotState = {
        "user_id": user_id,
        "current_query": message,
        "conversation_history": conversation_history or [],
        "intent_payload": None,
        "partial_payload": partial_payload,
        "response": None,
        "context": {},
        "needs_clarification": False,
        "options": None,
        "content_data": None
    }
    
    # Run the graph
    result = chatbot.graph.invoke(initial_state)
    
    # Update cache with new partial payload if clarification is needed
    if result.get("needs_clarification") and result.get("partial_payload"):
        _partial_payload_cache[user_id] = result["partial_payload"]
    elif not result.get("needs_clarification"):
        # Clear cache when request is complete
        _partial_payload_cache.pop(user_id, None)
    
    response = result.get("response", "I apologize, but I couldn't process your request.")
    options = result.get("options")
    content_data = result.get("content_data")
    
    # Debug: Log what's in the result
    logger.info(f"🔍 Stream function - Result keys: {list(result.keys())}")
    logger.info(f"   Result has 'content_data' key: {'content_data' in result}")
    logger.info(f"   content_data value: {content_data}")
    logger.info(f"   content_data type: {type(content_data)}")
    if content_data:
        logger.info(f"   content_data keys: {list(content_data.keys()) if isinstance(content_data, dict) else 'N/A'}")
        logger.info(f"   content_data images: {content_data.get('images') if isinstance(content_data, dict) else 'N/A'}")
    
    # For now, yield the full response in chunks
    # Can be enhanced later for true streaming
    chunk_size = 10
    for i in range(0, len(response), chunk_size):
        yield response[i:i + chunk_size]
    
    # Yield options at the end if they exist
    if options:
        yield f"\n\nOPTIONS:{json.dumps(options)}"
    
    # Yield content_data at the end if it exists
    if content_data:
        logger.info(f"📤 Yielding CONTENT_DATA in stream: {json.dumps(content_data, default=str)[:200]}...")
        logger.info(f"   Images in content_data: {content_data.get('images')}")
        try:
            content_data_json = json.dumps(content_data, default=str)
            yield f"\n\nCONTENT_DATA:{content_data_json}"
            logger.info(f"✅ Successfully yielded CONTENT_DATA")
        except Exception as e:
            logger.error(f"❌ Error serializing content_data: {e}", exc_info=True)
    else:
        logger.warning(f"⚠️ content_data is None or empty - not yielding CONTENT_DATA")
        logger.warning(f"   Result keys: {list(result.keys())}")
        logger.warning(f"   Checking result directly: {result.get('content_data', 'NOT_FOUND')}")



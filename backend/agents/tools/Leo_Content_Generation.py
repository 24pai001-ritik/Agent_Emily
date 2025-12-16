"""
Leo Content Generation Tool
Handles all content generation requests (social media, blog, email, whatsapp, ads)
"""

import logging
import os
import json
import re
import asyncio
from typing import Dict, Any, Optional, List
from agents.emily import ContentGenerationPayload
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

def execute_content_generation(payload: ContentGenerationPayload, user_id: str) -> Dict[str, Any]:
    """
    Execute content generation based on the payload
    
    Args:
        payload: ContentGenerationPayload with content type and details
        user_id: User ID for the request
        
    Returns:
        Dict with success, data, clarifying_question, or error
    """
    try:
        # Validate that we have a content type
        if not payload.type:
            return {
                "success": False,
                "clarifying_question": "What type of content would you like to generate? (social media, blog, email, whatsapp, or ads)"
            }
        
        # Route to appropriate handler based on type
        if payload.type == "social_media":
            return asyncio.run(_handle_social_media_async(payload.social_media, user_id))
        elif payload.type == "blog":
            return _handle_blog(payload.blog, user_id)
        elif payload.type == "email":
            return _handle_email(payload.email, user_id)
        elif payload.type == "whatsapp":
            return _handle_whatsapp(payload.whatsapp, user_id)
        elif payload.type == "ads":
            return _handle_ads(payload.ads, user_id)
        else:
            return {
                "success": False,
                "error": f"Unknown content type: {payload.type}"
            }
            
    except Exception as e:
        logger.error(f"Error in execute_content_generation: {e}")
        return {
            "success": False,
            "error": str(e)
        }

async def _handle_social_media_async(payload: Optional[Any], user_id: str) -> Dict[str, Any]:
    """Handle social media content generation - replicates CustomContentAgent logic using payload"""
    if not payload:
        return {
            "success": False,
            "clarifying_question": "I need more details about your social media post. Which platform(s) would you like to post on? (facebook, instagram, youtube, linkedin, twitter, pinterest)"
        }
    
    # Check for required fields
    if not payload.platform:
        return {
            "success": False,
            "clarifying_question": "Which platform(s) would you like to create content for? (facebook, instagram, youtube, linkedin, twitter, pinterest)"
        }
    
    if not payload.content_type:
        return {
            "success": False,
            "clarifying_question": "What type of content would you like to create? (post, reel, video, story, carousel)"
        }
    
    if not payload.idea:
        return {
            "success": False,
            "clarifying_question": "What's the topic or idea for your content? (e.g., product launch, company update, tip, announcement)"
        }
    
    try:
        import openai
        
        # Initialize OpenAI client
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return {
                "success": False,
                "error": "OpenAI API key not configured"
            }
        
        client = openai.OpenAI(api_key=openai_api_key)
        
        # Get the first platform (for now, we'll generate for the first platform)
        platform = payload.platform[0] if isinstance(payload.platform, list) else payload.platform
        content_type = payload.content_type
        user_description = payload.idea or ""
        
        # Load business context
        business_context = _load_business_context(user_id)
        
        # Handle media
        has_media = False
        media_url = None
        media_type = None
        image_analysis = ""
        
        if payload.media == "upload" and payload.media_file:
            has_media = True
            # Upload the media file to content_images bucket
            try:
                uploaded_url = await _upload_media_to_content_images(payload.media_file, user_id)
                if uploaded_url:
                    media_url = uploaded_url
                    logger.info(f"✅ Uploaded media to content_images bucket: {media_url}")
                else:
                    # Fallback to original URL if upload fails
                    media_url = payload.media_file
                    logger.warning(f"⚠️ Failed to upload media to content_images, using original URL: {media_url}")
            except Exception as e:
                logger.error(f"Error uploading media to content_images: {e}")
                # Fallback to original URL
                media_url = payload.media_file
                logger.warning(f"Using original media URL as fallback: {media_url}")
            
            media_type = "image"  # Default to image, can be enhanced to detect video
            # Analyze image if available
            try:
                image_analysis = asyncio.run(_analyze_uploaded_image(media_url, user_description, business_context))
            except Exception as e:
                logger.warning(f"Image analysis failed: {e}")
                image_analysis = ""
        elif payload.media == "generate":
            has_media = True
            media_type = "image"
            # Media will be generated separately if needed
        
        # Create enhanced content prompt
        prompt = _create_content_prompt(
            user_description, platform, content_type, business_context, 
            image_analysis, has_media
        )
        
        # Prepare messages for content generation
        messages = [
            {"role": "system", "content": "You are an expert social media content creator. Generate engaging, platform-optimized content that incorporates visual elements when provided. CRITICAL: Return ONLY a valid JSON object with the exact fields specified. Do NOT include any markdown formatting, code blocks, or nested JSON. The response must be pure JSON that can be parsed directly."},
            {"role": "user", "content": prompt}
        ]
        
        # Add image to messages if available
        if has_media and media_url and media_type == "image":
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here's the image to incorporate into the content:"},
                    {"type": "image_url", "image_url": {"url": media_url}}
                ]
            })
        
        # Generate content using OpenAI
        try:
            response = client.chat.completions.create(
                model="gpt-4o",  # Use vision-capable model
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                timeout=60
            )
            generated_text = response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error generating content with images: {e}")
            
            # If timeout or image download error, try without images
            if "timeout" in error_msg.lower() or "invalid_image_url" in error_msg.lower() or "downloading" in error_msg.lower():
                logger.warning("Image download timeout, generating content without images")
                text_only_messages = [
                    {"role": "system", "content": messages[0]["content"]},
                    {"role": "user", "content": prompt + "\n\nNote: Image is available but couldn't be analyzed due to timeout. Generate content based on the description and theme."}
                ]
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=text_only_messages,
                    temperature=0.7,
                    max_tokens=1000
                )
                generated_text = response.choices[0].message.content
            else:
                raise e
        
        # Parse the generated content
        try:
            content_data = json.loads(generated_text)
        except json.JSONDecodeError:
            # If not JSON, create a structured response
            content_data = {
                "content": generated_text,
                "title": f"{content_type} for {platform}",
                "hashtags": _extract_hashtags(generated_text),
                "post_type": "image" if has_media else "text"
            }
        
        # Extract structured content
        title = content_data.get("title", f"{content_type} for {platform}")
        content = content_data.get("content", "")
        hashtags = content_data.get("hashtags", [])
        
        # Extract images
        images = []
        if has_media and media_url:
            images = [media_url]
            logger.info(f"Using uploaded media URL: {media_url}")
        
        # Generate image if media is "generate"
        generated_image_url = None
        if payload.media == "generate":
            try:
                logger.info(f"🖼️ Starting image generation for user {user_id}, platform: {platform}, content_type: {content_type}")
                logger.info(f"   Title: {title[:50]}...")
                logger.info(f"   Content preview: {content[:100]}...")
                generated_image_url = await _generate_image_for_content(
                    user_id, title, content, platform, content_type, business_context, hashtags
                )
                if generated_image_url:
                    # Ensure it's a valid string URL
                    if isinstance(generated_image_url, str) and len(generated_image_url) > 0:
                        images = [generated_image_url]
                        logger.info(f"✅ Generated image URL successfully: {generated_image_url}")
                        logger.info(f"   Images array now contains: {images}")
                        logger.info(f"   Images array type: {type(images)}")
                        logger.info(f"   Images array length: {len(images)}")
                    else:
                        logger.warning(f"⚠️ Generated URL is invalid: {generated_image_url} (type: {type(generated_image_url)})")
                        images = []
                else:
                    logger.warning("⚠️ Image generation returned None - no image URL was generated")
                    logger.warning(f"   Images array remains: {images}")
            except Exception as e:
                logger.error(f"❌ Error generating image: {e}", exc_info=True)
                logger.error(f"   Images array remains: {images}")
                # Continue without image if generation fails
        else:
            logger.info(f"Media option is '{payload.media}' - skipping image generation")
            logger.info(f"   Images array: {images}")
        
        # Save to Created_Content table
        saved_content_id = None
        try:
            content_record = {
                "user_id": user_id,
                "platform": platform,
                "content_type": content_type,
                "title": title,
                "content": content,
                "hashtags": hashtags or [],
                "images": images or [],
                "status": "generated",
                "metadata": {
                    "generated_by": "leo_content_generation",
                    "media_type": media_type if has_media else None,
                    "media_source": "generated" if payload.media == "generate" else ("uploaded" if payload.media == "upload" else None)
                }
            }
            
            if supabase:
                save_response = supabase.table("created_content").insert(content_record).execute()
                if save_response.data and len(save_response.data) > 0:
                    saved_content_id = save_response.data[0]["id"]
                    logger.info(f"Saved generated content to Created_Content table with ID: {saved_content_id}")
                else:
                    logger.warning("Failed to save content to Created_Content table - no data returned")
            else:
                logger.warning("Supabase client not initialized - content not saved to database")
        except Exception as save_error:
            logger.error(f"Error saving content to Created_Content table: {save_error}", exc_info=True)
            # Continue even if save fails
        
        # Ensure images is always a list
        if not images:
            images = []
        elif not isinstance(images, list):
            images = [images] if images else []
        
        # Log what we're returning
        logger.info(f"📤 Returning content generation result:")
        logger.info(f"  - Title: {title}")
        logger.info(f"  - Content length: {len(content)} chars")
        logger.info(f"  - Hashtags: {hashtags}")
        logger.info(f"  - Images: {images}")
        logger.info(f"  - Images type: {type(images)}")
        logger.info(f"  - Images count: {len(images)}")
        if images:
            for idx, img_url in enumerate(images):
                logger.info(f"    Image {idx + 1}: {img_url} (type: {type(img_url)})")
        logger.info(f"  - Platform: {platform}")
        logger.info(f"  - Content type: {content_type}")
        
        # Update the payload with saved_content_id in the content field
        updated_payload = None
        if payload and saved_content_id:
            # Create a copy of the payload and update the content field
            try:
                # Convert payload to dict if it's a Pydantic model
                if hasattr(payload, 'model_dump'):
                    payload_dict = payload.model_dump()
                elif hasattr(payload, 'dict'):
                    payload_dict = payload.dict()
                else:
                    payload_dict = dict(payload) if payload else {}
                
                # Update the content field with saved_content_id
                payload_dict["content"] = saved_content_id
                updated_payload = payload_dict
                logger.info(f"📝 Updated payload with content (saved_content_id): {saved_content_id}")
            except Exception as e:
                logger.warning(f"Could not update payload with content field: {e}")
        
        result_data = {
            "success": True,
            "data": {
                "title": title,
                "content": content,
                "hashtags": hashtags or [],
                "images": images,  # Always a list
                "platform": platform,
                "content_type": content_type,
                "saved_content_id": saved_content_id
            },
            "payload": updated_payload  # Include the full updated payload
        }
        
        # Log the final result structure
        logger.info(f"📦 Final result structure:")
        logger.info(f"  - Result keys: {result_data.keys()}")
        logger.info(f"  - Data keys: {result_data['data'].keys()}")
        logger.info(f"  - Data['images']: {result_data['data']['images']}")
        logger.info(f"  - Data['images'] type: {type(result_data['data']['images'])}")
        logger.info(f"  - Payload included: {updated_payload is not None}")
        if updated_payload:
            logger.info(f"  - Payload content field: {updated_payload.get('content')}")
        
        return result_data
            
    except Exception as e:
        logger.error(f"Error generating social media content: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Failed to generate content: {str(e)}"
        }

def _load_business_context(user_id: str) -> Dict[str, Any]:
    """Load business context from user profile"""
    try:
        if not supabase:
            return _get_default_business_context()
        
        # Get user profile from Supabase including embeddings
        response = supabase.table("profiles").select("*, profile_embedding").eq("id", user_id).execute()
        
        if response.data and len(response.data) > 0:
            profile_data = response.data[0]
            # Use embedding context utility if available
            try:
                from utils.embedding_context import get_profile_context_with_embedding
                return get_profile_context_with_embedding(profile_data)
            except ImportError:
                # Fallback to basic extraction
                return {
                    "business_name": profile_data.get("business_name", ""),
                    "industry": profile_data.get("industry", ""),
                    "target_audience": profile_data.get("target_audience", ""),
                    "brand_voice": profile_data.get("brand_voice", ""),
                    "content_goals": profile_data.get("content_goals", []),
                    "brand_personality": profile_data.get("brand_personality", ""),
                    "brand_values": profile_data.get("brand_values", [])
                }
        else:
            logger.warning(f"No profile found for user {user_id}")
            return _get_default_business_context()
            
    except Exception as e:
        logger.error(f"Error loading business context for user {user_id}: {e}")
        return _get_default_business_context()

def _get_default_business_context() -> Dict[str, Any]:
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

def _create_content_prompt(description: str, platform: str, content_type: str, 
                          business_context: Dict[str, Any], image_analysis: str, 
                          has_media: bool) -> str:
    """Create an enhanced prompt for content generation"""
    base_prompt = f"""
Create a {content_type} for {platform} based on this description: "{description}"

Business Context:
- Business Name: {business_context.get('business_name', 'Not specified')}
- Industry: {business_context.get('industry', 'Not specified')}
- Target Audience: {business_context.get('target_audience', 'General audience')}
- Brand Voice: {business_context.get('brand_voice', 'Professional and friendly')}
- Brand Personality: {business_context.get('brand_personality', 'Approachable and trustworthy')}
"""
    
    if has_media and image_analysis:
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
- Create a compelling narrative that connects the image to your business
- Use the visual elements to enhance the message

CRITICAL INSTRUCTIONS:
- Return ONLY a valid JSON object
- Do NOT use markdown code blocks (no ```json or ```)
- Do NOT include any text before or after the JSON
- The JSON must be parseable directly
- Use these exact field names:

{{
  "content": "The main post content that references the image",
  "title": "A catchy title",
  "hashtags": ["array", "of", "relevant", "hashtags"],
  "call_to_action": "Suggested call to action"
}}
"""
    else:
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
- Do NOT include any text before or after the JSON
- The JSON must be parseable directly
- Use these exact field names:

{{
  "content": "The main post content",
  "title": "A catchy title",
  "hashtags": ["array", "of", "relevant", "hashtags"],
  "call_to_action": "Suggested call to action"
}}
"""
    
    return enhanced_prompt

async def _analyze_uploaded_image(image_url: str, user_description: str, business_context: Dict[str, Any]) -> str:
    """Analyze uploaded image using vision model"""
    try:
        import httpx
        import base64
        import openai
        
        # Download image and convert to base64
        async with httpx.AsyncClient(timeout=30.0) as client:
            image_response = await client.get(image_url)
            image_response.raise_for_status()
            image_data = image_response.content
            
            # Convert to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Determine image format
            if image_url.lower().endswith('.png'):
                image_format = 'png'
            elif image_url.lower().endswith(('.jpg', '.jpeg')):
                image_format = 'jpeg'
            else:
                image_format = 'jpeg'  # Default
            
            data_url = f"data:image/{image_format};base64,{base64_image}"
            
            # Analyze with OpenAI vision
            openai_api_key = os.getenv("OPENAI_API_KEY")
            client_openai = openai.OpenAI(api_key=openai_api_key)
            
            analysis_prompt = f"""Analyze this image in the context of:
- User's content idea: "{user_description}"
- Business: {business_context.get('business_name', 'Not specified')}
- Industry: {business_context.get('industry', 'Not specified')}

Describe the visual elements, colors, composition, mood, and how it relates to the business context. Provide insights that can be used to create engaging social media content."""
            
            response = client_openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": [
                        {"type": "text", "text": analysis_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]}
                ],
                max_tokens=500
            )
            
            return response.choices[0].message.content
            
    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return f"Image analysis failed: {str(e)}"

def _extract_hashtags(text: str) -> List[str]:
    """Extract hashtags from text"""
    hashtags = re.findall(r'#\w+', text)
    return hashtags[:10]  # Limit to 10 hashtags

async def _upload_media_to_content_images(media_url: str, user_id: str) -> Optional[str]:
    """Upload media file from URL to content_images bucket"""
    try:
        import httpx
        import uuid
        from datetime import datetime
        
        if not supabase:
            logger.error("Supabase client not initialized")
            return None
        
        logger.info(f"📤 Downloading media from URL: {media_url}")
        
        # Download the file
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(media_url)
            response.raise_for_status()
            file_content = response.content
            content_type = response.headers.get("content-type", "image/jpeg")
        
        logger.info(f"✅ Downloaded media: {len(file_content)} bytes, type: {content_type}")
        
        # Determine file extension from content type or URL
        file_ext = "png"
        if "image/jpeg" in content_type or "image/jpg" in content_type:
            file_ext = "jpg"
        elif "image/png" in content_type:
            file_ext = "png"
        elif "image/gif" in content_type:
            file_ext = "gif"
        elif "image/webp" in content_type:
            file_ext = "webp"
        elif "video/" in content_type:
            file_ext = "mp4"
        else:
            # Try to extract from URL
            if ".jpg" in media_url.lower() or ".jpeg" in media_url.lower():
                file_ext = "jpg"
            elif ".png" in media_url.lower():
                file_ext = "png"
            elif ".gif" in media_url.lower():
                file_ext = "gif"
            elif ".webp" in media_url.lower():
                file_ext = "webp"
            elif ".mp4" in media_url.lower():
                file_ext = "mp4"
        
        # Generate filename
        filename = f"{user_id}_{uuid.uuid4().hex[:8]}.{file_ext}"
        file_path = f"uploaded/{filename}"
        
        logger.info(f"📤 Uploading to content_images bucket: {file_path}")
        
        # Upload to content_images bucket
        storage_response = supabase.storage.from_("content_images").upload(
            file_path,
            file_content,
            file_options={"content-type": content_type, "upsert": "false"}
        )
        
        if hasattr(storage_response, 'error') and storage_response.error:
            logger.error(f"Storage upload error: {storage_response.error}")
            return None
        
        # Get public URL
        public_url = supabase.storage.from_("content_images").get_public_url(file_path)
        
        if not public_url or not isinstance(public_url, str):
            logger.error(f"Invalid public URL returned: {public_url}")
            return None
        
        logger.info(f"✅ Media uploaded successfully to content_images bucket")
        logger.info(f"   File path: {file_path}")
        logger.info(f"   Public URL: {public_url}")
        
        return public_url
        
    except Exception as e:
        logger.error(f"Error uploading media to content_images bucket: {e}", exc_info=True)
        return None

async def _generate_image_for_content(user_id: str, title: str, content: str, 
                                     platform: str, content_type: str, 
                                     business_context: Dict[str, Any],
                                     hashtags: List[str] = None) -> Optional[str]:
    """Generate image for content using Gemini directly - simplified without campaigns"""
    try:
        import google.generativeai as genai
        import uuid
        import base64
        from datetime import datetime
        
        # Check for required environment variables
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            logger.warning("GEMINI_API_KEY not configured - cannot generate images")
            return None
        
        if not supabase:
            logger.error("Supabase client not initialized")
            return None
        
        # Configure Gemini
        genai.configure(api_key=gemini_api_key)
        gemini_image_model = 'gemini-2.5-flash-image-preview'
        
        # Get user profile for brand colors
        user_profile = {}
        try:
            profile_response = supabase.table("profiles").select("*").eq("id", user_id).execute()
            if profile_response.data and len(profile_response.data) > 0:
                user_profile = profile_response.data[0]
        except Exception as e:
            logger.warning(f"Could not fetch user profile: {e}")
        
        # Extract brand colors
        business_name = user_profile.get('business_name') or business_context.get('business_name', 'Business')
        primary_color = user_profile.get('primary_color', '')
        secondary_color = user_profile.get('secondary_color', '')
        additional_colors = user_profile.get('additional_colors', [])
        
        # Generate image prompt using Gemini (or create a simple one)
        try:
            # Try to generate a detailed prompt using Gemini
            prompt_model = genai.GenerativeModel('gemini-2.5-flash')
            prompt_prompt = f"""Create a detailed, visual image generation prompt for a social media post image.

Content: {content[:500]}
Platform: {platform}
Content Type: {content_type}
Business: {business_name}
Industry: {business_context.get('industry', 'General')}

Create a vivid, descriptive prompt that will generate a professional, engaging image suitable for {platform}. 
Focus on visual elements, composition, mood, and style that matches the content and platform.
Keep it concise but descriptive (2-3 sentences max)."""
            
            prompt_response = prompt_model.generate_content(prompt_prompt)
            image_prompt = prompt_response.text.strip()
            logger.info(f"Generated image prompt: {image_prompt[:100]}...")
        except Exception as e:
            logger.warning(f"Failed to generate prompt with Gemini, using fallback: {e}")
            # Fallback prompt
            color_context = ""
            if primary_color:
                color_context = f" Use primary brand color {primary_color}"
            if secondary_color:
                color_context += f" and secondary color {secondary_color}"
            image_prompt = f"Professional {platform} post image for {business_name} featuring: {content[:100]}.{color_context}"
        
        # Build brand colors instruction
        brand_colors_instruction = ""
        if primary_color or secondary_color or (additional_colors and any([c for c in additional_colors if c])):
            colors_section = []
            if primary_color:
                colors_section.append(f"Primary: {primary_color}")
            if secondary_color:
                colors_section.append(f"Secondary: {secondary_color}")
            if additional_colors and isinstance(additional_colors, list):
                additional_list = [c for c in additional_colors if c]
                if additional_list:
                    colors_section.append(f"Additional: {', '.join(additional_list)}")
            
            brand_colors_instruction = f"""
CRITICAL BRAND COLOR REQUIREMENTS (MUST FOLLOW):
- PRIMARY COLOR: Use {primary_color} as the dominant color in the design
- SECONDARY COLOR: Use {secondary_color} as accent colors
{f"- ADDITIONAL COLORS: {', '.join([c for c in additional_colors if c])}" if additional_colors and any([c for c in additional_colors if c]) else ""}
- The image MUST primarily use these exact brand colors in the color palette
- Primary color should dominate backgrounds, main elements, or key visual areas
- Secondary color should be used for accents, highlights, borders, or complementary elements
- Create visual harmony using this specific brand color scheme
- Do NOT deviate from these brand colors - maintain strict brand consistency
- Apply these colors to backgrounds, text, graphics, borders, or any visual elements as appropriate
"""
        
        # Determine image size based on platform
        image_size = "1024x1024"  # Default square
        if platform.lower() in ["youtube"]:
            image_size = "1792x1024"  # Landscape
        
        # Create full Gemini prompt
        gemini_prompt = f"""
You are a professional graphic designer and image generator. Create a high-quality social media post image based on the following requirements.

IMAGE GENERATION PROMPT: {image_prompt}

{brand_colors_instruction}

DESIGN REQUIREMENTS:
1. Generate a NEW IMAGE that matches the prompt description
2. Create a visually appealing, professional image suitable for social media
3. Use high resolution and professional quality
4. Ensure the image is engaging and eye-catching
5. Apply modern design principles and good composition
6. Use appropriate colors, lighting, and visual elements - MUST follow brand color requirements above
7. Make sure the image tells a story and conveys the intended message
8. Ensure the image is optimized for social media platforms
9. Create a cohesive and professional design that reflects the brand identity
10. OUTPUT: Return the final generated image, not text description

TECHNICAL SPECIFICATIONS:
- High resolution and professional quality
- Suitable for social media posting
- Engaging and visually appealing
- Professional composition and lighting
- Clear and impactful visual elements
- Brand colors must be prominently and correctly applied

OUTPUT: A single, professionally designed image that matches the prompt requirements with high visual quality and strict adherence to brand colors.
"""
        
        # Generate image using Gemini
        logger.info(f"Generating image with Gemini model: {gemini_image_model}")
        start_time = datetime.now()
        
        try:
            response = genai.GenerativeModel(gemini_image_model).generate_content(
                contents=[gemini_prompt],
            )
            
            # Extract image data from response
            image_data = None
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data is not None and part.inline_data.data:
                            image_data = part.inline_data.data
                            break
            
            if not image_data:
                raise Exception("No image data returned from Gemini")
            
            # Convert to bytes if needed
            if isinstance(image_data, bytes):
                image_bytes = image_data
            else:
                image_bytes = base64.b64decode(image_data)
            
            # Upload to Supabase storage - content_images bucket
            filename = f"{user_id}_{uuid.uuid4().hex[:8]}.png"
            file_path = f"generated/{filename}"
            
            logger.info(f"Uploading image to content_images bucket: {file_path}, size: {len(image_bytes)} bytes")
            
            try:
                storage_response = supabase.storage.from_("content_images").upload(
                    file_path,
                    image_bytes,
                    file_options={"content-type": "image/png", "upsert": "false"}
                )
                
                if hasattr(storage_response, 'error') and storage_response.error:
                    logger.error(f"Storage upload error: {storage_response.error}")
                    raise Exception(f"Failed to upload image: {storage_response.error}")
                
                # Get public URL
                public_url = supabase.storage.from_("content_images").get_public_url(file_path)
                
                # Ensure URL is a string and properly formatted
                if not public_url or not isinstance(public_url, str):
                    logger.error(f"Invalid public URL returned: {public_url} (type: {type(public_url)})")
                    raise Exception("Failed to get valid public URL from Supabase storage")
                
                # Log the full URL details
                logger.info(f"✅ Image uploaded successfully to content_images bucket")
                logger.info(f"   File path: {file_path}")
                logger.info(f"   Public URL: {public_url}")
                logger.info(f"   URL type: {type(public_url)}")
                logger.info(f"   URL length: {len(public_url)}")
                
            except Exception as upload_error:
                logger.error(f"Error uploading to content_images bucket: {upload_error}", exc_info=True)
                raise
            
            generation_time = int((datetime.now() - start_time).total_seconds())
            logger.info(f"✅ Image generation completed successfully in {generation_time}s")
            logger.info(f"   Final public URL to return: {public_url}")
            
            return public_url
            
        except Exception as e:
            logger.error(f"Error generating image with Gemini: {e}", exc_info=True)
            return None
            
    except Exception as e:
        logger.error(f"Error generating image for content: {e}", exc_info=True)
        return None

def _handle_blog(payload: Optional[Any], user_id: str) -> Dict[str, Any]:
    """Handle blog content generation"""
    if not payload:
        return {
            "success": False,
            "clarifying_question": "I need more details about your blog post. What platform will you publish on? (wordpress, shopify, wix, html)"
        }
    
    if not payload.topic:
        return {
            "success": False,
            "clarifying_question": "What topic would you like to write about?"
        }
    
    # TODO: Integrate with blog writing agent
    # For now, save a placeholder entry
    saved_content_id = None
    try:
        if supabase:
            content_record = {
                "user_id": user_id,
                "platform": payload.platform if hasattr(payload, 'platform') else None,
                "content_type": "blog",
                "title": f"Blog post about {payload.topic}",
                "content": f"Blog post content about '{payload.topic}'. This feature is being set up.",
                "hashtags": [],
                "images": [],
                "status": "generated",
                "metadata": {
                    "generated_by": "leo_content_generation",
                    "topic": payload.topic,
                    "platform": payload.platform if hasattr(payload, 'platform') else None
                }
            }
            save_response = supabase.table("created_content").insert(content_record).execute()
            if save_response.data and len(save_response.data) > 0:
                saved_content_id = save_response.data[0]["id"]
                logger.info(f"Saved blog content to Created_Content table with ID: {saved_content_id}")
    except Exception as save_error:
        logger.error(f"Error saving blog content to Created_Content table: {save_error}", exc_info=True)
    
    return {
        "success": True,
        "data": {
            "message": f"I'll help you create a blog post about '{payload.topic}'. This feature is being set up.",
            "saved_content_id": saved_content_id
        }
    }

def _handle_email(payload: Optional[Any], user_id: str) -> Dict[str, Any]:
    """Handle email content generation"""
    if not payload:
        return {
            "success": False,
            "clarifying_question": "I need more details about your email. Who should I send it to?"
        }
    
    if not payload.email_address:
        return {
            "success": False,
            "clarifying_question": "What email address should I send this to?"
        }
    
    if not payload.content:
        return {
            "success": False,
            "clarifying_question": "What should the email content be?"
        }
    
    # Save email content
    saved_content_id = None
    try:
        if supabase:
            content_record = {
                "user_id": user_id,
                "platform": None,
                "content_type": "email",
                "title": payload.subject if hasattr(payload, 'subject') else f"Email to {payload.email_address}",
                "content": payload.content,
                "hashtags": [],
                "images": payload.attachments if hasattr(payload, 'attachments') and payload.attachments else [],
                "status": "generated",
                "metadata": {
                    "generated_by": "leo_content_generation",
                    "email_address": payload.email_address,
                    "task": payload.task if hasattr(payload, 'task') else None,
                    "attachments": payload.attachments if hasattr(payload, 'attachments') else []
                }
            }
            save_response = supabase.table("created_content").insert(content_record).execute()
            if save_response.data and len(save_response.data) > 0:
                saved_content_id = save_response.data[0]["id"]
                logger.info(f"Saved email content to Created_Content table with ID: {saved_content_id}")
    except Exception as save_error:
        logger.error(f"Error saving email content to Created_Content table: {save_error}", exc_info=True)
    
    # TODO: Integrate with email sending functionality
    return {
        "success": True,
        "data": {
            "message": f"I'll help you send an email to {payload.email_address}. This feature is being set up.",
            "saved_content_id": saved_content_id
        }
    }

def _handle_whatsapp(payload: Optional[Any], user_id: str) -> Dict[str, Any]:
    """Handle WhatsApp message generation"""
    if not payload:
        return {
            "success": False,
            "clarifying_question": "I need more details about your WhatsApp message. What phone number should I send it to?"
        }
    
    if not payload.phone_number:
        return {
            "success": False,
            "clarifying_question": "What phone number should I send this WhatsApp message to? (include country code, e.g., +919876543210)"
        }
    
    if not payload.text:
        return {
            "success": False,
            "clarifying_question": "What message would you like to send?"
        }
    
    # Save WhatsApp content
    saved_content_id = None
    try:
        if supabase:
            content_record = {
                "user_id": user_id,
                "platform": "whatsapp",
                "content_type": "whatsapp",
                "title": f"WhatsApp message to {payload.phone_number}",
                "content": payload.text,
                "hashtags": [],
                "images": [payload.attachment] if hasattr(payload, 'attachment') and payload.attachment else [],
                "status": "generated",
                "metadata": {
                    "generated_by": "leo_content_generation",
                    "phone_number": payload.phone_number,
                    "attachment": payload.attachment if hasattr(payload, 'attachment') else None
                }
            }
            save_response = supabase.table("created_content").insert(content_record).execute()
            if save_response.data and len(save_response.data) > 0:
                saved_content_id = save_response.data[0]["id"]
                logger.info(f"Saved WhatsApp content to Created_Content table with ID: {saved_content_id}")
    except Exception as save_error:
        logger.error(f"Error saving WhatsApp content to Created_Content table: {save_error}", exc_info=True)
    
    # TODO: Integrate with WhatsApp sending functionality
    return {
        "success": True,
        "data": {
            "message": f"I'll help you send a WhatsApp message to {payload.phone_number}. This feature is being set up.",
            "saved_content_id": saved_content_id
        }
    }

def _handle_ads(payload: Optional[Any], user_id: str) -> Dict[str, Any]:
    """Handle ads creation"""
    if not payload:
        return {
            "success": False,
            "clarifying_question": "I need more details about your ad campaign. Which platform? (meta, google, linkedin, youtube)"
        }
    
    if not payload.platform:
        return {
            "success": False,
            "clarifying_question": "Which platform would you like to create ads for? (meta, google, linkedin, youtube)"
        }
    
    # Save ads content
    saved_content_id = None
    try:
        if supabase:
            content_record = {
                "user_id": user_id,
                "platform": payload.platform[0] if isinstance(payload.platform, list) else payload.platform,
                "content_type": "ads",
                "title": f"Ad campaign for {payload.platform}",
                "content": f"Ad content for {payload.platform}. This feature is being set up.",
                "hashtags": [],
                "images": [],
                "status": "generated",
                "metadata": {
                    "generated_by": "leo_content_generation",
                    "platform": payload.platform[0] if isinstance(payload.platform, list) else payload.platform,
                    "ad_type": payload.ad_type if hasattr(payload, 'ad_type') else None
                }
            }
            save_response = supabase.table("created_content").insert(content_record).execute()
            if save_response.data and len(save_response.data) > 0:
                saved_content_id = save_response.data[0]["id"]
                logger.info(f"Saved ads content to Created_Content table with ID: {saved_content_id}")
    except Exception as save_error:
        logger.error(f"Error saving ads content to Created_Content table: {save_error}", exc_info=True)
    
    # TODO: Integrate with ads creation agent
    return {
        "success": True,
        "data": {
            "message": f"I'll help you create ads for {payload.platform}. This feature is being set up.",
            "saved_content_id": saved_content_id
        }
    }


from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any
import os
import logging
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

from auth import get_current_user, User
from services.razorpay_service import RazorpayService
from schemas.subscription import (
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionStatusResponse,
    MigrationStatusResponse
)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])

# Initialize Razorpay service
razorpay_service = RazorpayService()

@router.get("/test-webhook")
async def test_webhook():
    """Test webhook endpoint"""
    return JSONResponse(content={"success": True, "message": "Webhook endpoint is working"})

@router.get("/test-razorpay")
async def test_razorpay():
    """Test Razorpay connectivity"""
    try:
        # Test if Razorpay client can be initialized
        from services.razorpay_service import RazorpayService
        razorpay_service = RazorpayService()
        
        # Test a simple API call
        plans = razorpay_service.client.plan.all()
        
        return JSONResponse(content={
            "success": True,
            "message": "Razorpay connection successful",
            "plans_count": len(plans.get('items', []))
        })
        
    except Exception as e:
        logger.error(f"Razorpay test failed: {e}")
        return JSONResponse(content={
            "success": False,
            "error": str(e)
        }, status_code=500)

@router.get("/test-customers")
async def test_customers():
    """Test Razorpay customers"""
    try:
        from services.razorpay_service import RazorpayService
        razorpay_service = RazorpayService()
        
        # Get all customers
        customers = razorpay_service.client.customer.all()
        
        return JSONResponse(content={
            "success": True,
            "customers": customers.get('items', []),
            "total_count": customers.get('count', 0)
        })
        
    except Exception as e:
        logger.error(f"Razorpay customers test failed: {e}")
        return JSONResponse(content={
            "success": False,
            "error": str(e)
        }, status_code=500)

@router.get("/plans")
async def get_subscription_plans():
    """Get all available subscription plans"""
    try:
        result = supabase.table("subscription_plans").select("*").eq("is_active", True).execute()
        plans = result.data
        
        plans_data = []
        for plan in plans:
            plans_data.append({
                "id": plan["id"],
                "name": plan["name"],
                "display_name": plan["display_name"],
                "price_monthly": plan["price_monthly"],
                "price_yearly": plan["price_yearly"],
                "features": plan["features"],
                "monthly_price_display": f"₹{plan['price_monthly']}",
                "yearly_price_display": f"₹{plan['price_yearly']}",
                "razorpay_plan_id_monthly": plan.get("razorpay_plan_id_monthly"),
                "razorpay_plan_id_yearly": plan.get("razorpay_plan_id_yearly")
            })
        
        return JSONResponse(content={
            "success": True,
            "plans": plans_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching subscription plans: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription plans")

@router.get("/status")
async def get_subscription_status(
    current_user: User = Depends(get_current_user)
):
    """Get user's subscription status"""
    try:
        # Get user's subscription info from database
        result = supabase.rpc("get_user_subscription_info", {"user_uuid": current_user.id}).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_info = result.data[0]
        
        # Fetch subscription data directly from profiles table to ensure we have latest data
        # Using correct column names from schema: subscription_status, subscription_plan, subscription_end_date, subscription_start_date
        profile_result = supabase.table("profiles").select(
            "subscription_status, subscription_plan, subscription_end_date, subscription_start_date"
        ).eq("id", current_user.id).execute()
        
        subscription_end_date = None
        subscription_start_date = None
        subscription_plan = None
        subscription_status = None
        
        if profile_result.data:
            profile_data = profile_result.data[0]
            subscription_end_date = profile_data.get("subscription_end_date")
            subscription_start_date = profile_data.get("subscription_start_date")
            # Trim whitespace from plan name to prevent matching issues
            subscription_plan = profile_data.get("subscription_plan")
            if subscription_plan and isinstance(subscription_plan, str):
                subscription_plan = subscription_plan.strip()
            subscription_status = profile_data.get("subscription_status", "inactive")
        
        # Fallback to user_info if profile_result didn't have data
        if not subscription_plan:
            subscription_plan = user_info.get("subscription_plan", "")
            # Trim whitespace from plan name
            if subscription_plan and isinstance(subscription_plan, str):
                subscription_plan = subscription_plan.strip()
        if not subscription_status:
            subscription_status = user_info.get("subscription_status", "inactive")
        
        # IMPORTANT: Double-check expiration date even if database function says active
        # This is a safety net in case subscription_end_date wasn't properly checked
        # Also automatically update subscription_status to 'expired' for paid plans (not trial)
        has_active_subscription = user_info["has_active_subscription"]
        
        # Only check expiration for paid plans (not trial plans)
        # Trial plans use trial_expires_at, not subscription_end_date
        is_paid_plan = subscription_plan and subscription_plan not in ["free_trial", "trial", None, ""]
        
        # Check if subscription has expired (only for paid plans)
        # Ensure subscription_end_date is not None, empty string, or invalid
        has_valid_end_date = subscription_end_date and (
            isinstance(subscription_end_date, str) and subscription_end_date.strip() != '' or
            isinstance(subscription_end_date, datetime)
        )
        
        if has_valid_end_date and is_paid_plan:
            try:
                # Parse the end date - subscription_end_date is timestamp without time zone
                # Schema: subscription_end_date timestamp without time zone
                if isinstance(subscription_end_date, str):
                    # Handle ISO format strings (remove timezone info if present)
                    # Supabase returns timestamp without time zone as ISO string without 'Z'
                    end_date_str = subscription_end_date.replace('Z', '').replace('+00:00', '').replace('-00:00', '')
                    # Handle microseconds if present (e.g., 2025-01-12T05:55:59.883598)
                    try:
                        end_date = datetime.fromisoformat(end_date_str)
                    except ValueError:
                        # Try parsing without microseconds
                        end_date_str_no_micro = end_date_str.split('.')[0]
                        end_date = datetime.fromisoformat(end_date_str_no_micro)
                    # Ensure it's timezone-naive (timestamp without time zone)
                    if end_date.tzinfo:
                        end_date = end_date.replace(tzinfo=None)
                else:
                    # Already a datetime object
                    end_date = subscription_end_date
                    # Ensure it's timezone-naive
                    if hasattr(end_date, 'tzinfo') and end_date.tzinfo:
                        end_date = end_date.replace(tzinfo=None)
                
                # Compare with current UTC time (timezone-naive)
                now_utc = datetime.utcnow()
                
                # Log the comparison for debugging
                logger.info(
                    f"Comparing dates for user {current_user.id}: "
                    f"now_utc={now_utc}, end_date={end_date}, "
                    f"is_expired={now_utc > end_date}, plan={subscription_plan}"
                )
                
                if now_utc > end_date:
                    # Subscription expired - update status in database immediately
                    has_active_subscription = False
                    logger.warning(
                        f"User {current_user.id} has expired subscription "
                        f"(plan: {subscription_plan}, end_date: {subscription_end_date}, current: {now_utc})"
                    )
                    
                    # Update subscription_status to 'expired' in database immediately (only for paid plans)
                    # Using correct column name: subscription_status (character varying(20))
                    # Always update to ensure database is in sync, even if status is already 'expired'
                    try:
                        update_result = supabase.table("profiles").update({
                            "subscription_status": "expired"
                        }).eq("id", current_user.id).execute()
                        
                        if update_result.data:
                            logger.info(f"✅ Updated subscription_status to 'expired' for user {current_user.id} (plan: {subscription_plan})")
                            subscription_status = "expired"
                        else:
                            logger.warning(f"⚠️ Update returned no data for user {current_user.id} - status may already be 'expired'")
                            # Even if update returns no data, set status to expired for response
                            subscription_status = "expired"
                    except Exception as update_error:
                        logger.error(f"❌ Error updating subscription_status to expired: {update_error}")
                        # On error, still set status to expired for response
                        subscription_status = "expired"
                else:
                    # Subscription is still valid (end_date hasn't passed)
                    # ALWAYS set has_active_subscription to True when date hasn't passed
                    has_active_subscription = True
                    
                    # If status is 'expired' or not 'active', update it to 'active' since subscription is valid
                    if subscription_status != 'active':
                        logger.info(
                            f"🔄 User {current_user.id} subscription is still valid "
                            f"(plan: {subscription_plan}, end_date: {subscription_end_date}, current: {now_utc}), "
                            f"but status is '{subscription_status}'. Updating to 'active'..."
                        )
                        try:
                            # Always update to 'active' when subscription_end_date hasn't passed
                            update_result = supabase.table("profiles").update({
                                "subscription_status": "active"
                            }).eq("id", current_user.id).execute()
                            
                            if update_result.data:
                                logger.info(f"✅ Successfully updated subscription_status from '{subscription_status}' to 'active' for user {current_user.id} (plan: {subscription_plan})")
                                subscription_status = "active"
                            else:
                                logger.warning(f"⚠️ Update returned no data for user {current_user.id} - attempting to verify status")
                                # Even if update returns no data, set status to active for response since date is valid
                                subscription_status = "active"
                                # Try to verify by fetching updated profile
                                try:
                                    verify_result = supabase.table("profiles").select("subscription_status").eq("id", current_user.id).execute()
                                    if verify_result.data:
                                        actual_status = verify_result.data[0].get("subscription_status")
                                        logger.info(f"📋 Verified: actual status in DB is '{actual_status}' for user {current_user.id}")
                                        if actual_status == 'active':
                                            subscription_status = "active"
                                except Exception as verify_error:
                                    logger.error(f"Error verifying status: {verify_error}")
                        except Exception as update_error:
                            logger.error(f"❌ Error updating subscription_status to active: {update_error}")
                            # On error, still set status to active for response since date is valid
                            subscription_status = "active"
                    else:
                        # Status is already 'active' and subscription is valid - all good
                        logger.debug(f"✅ User {current_user.id} subscription is valid and status is already 'active'")
            except Exception as e:
                logger.error(f"Error parsing subscription_end_date for user {current_user.id}: {e}, raw_value={subscription_end_date}")
                # If we can't parse the date, check if status is 'active' - if so, assume it's valid
                if subscription_status == 'active':
                    has_active_subscription = True
                    logger.info(f"Assuming active subscription for user {current_user.id} due to 'active' status despite parse error")
                # Otherwise, trust the database function result
        
        # If subscription_end_date is None but status is 'active', ensure has_active_subscription is True
        if not subscription_end_date and subscription_status == 'active' and is_paid_plan:
            has_active_subscription = True
            logger.info(f"User {current_user.id} has active subscription without end_date, ensuring access")
        
        # Log final status for debugging
        logger.info(
            f"Final subscription status for user {current_user.id}: "
            f"status={subscription_status}, plan={subscription_plan}, "
            f"has_active={has_active_subscription}, end_date={subscription_end_date}"
        )
        
        return JSONResponse(content={
            "success": True,
            "status": subscription_status,  # Use updated status
            "plan": subscription_plan,
            "has_active_subscription": has_active_subscription,
            "migration_status": user_info["migration_status"],
            "grace_period_end": user_info["grace_period_end"],
            "days_left": user_info["days_left"],
            "subscription_end_date": subscription_end_date,
            "subscription_start_date": subscription_start_date
        })
        
    except Exception as e:
        logger.error(f"Error fetching subscription status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription status")

@router.get("/migration-status")
async def get_migration_status(
    current_user: User = Depends(get_current_user)
):
    """Get user's migration status for existing users"""
    try:
        # Check if user needs migration
        result = supabase.rpc("get_user_subscription_info", {"user_uuid": current_user.id}).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_info = result.data[0]
        
        migration_info = {
            "needs_migration": False,
            "migration_type": None,
            "current_access": "none",
            "grace_period_end": None,
            "days_left": 0
        }
        
        # Check if user is grandfathered
        if user_info["migration_status"] == 'grandfathered' and user_info["grace_period_end"]:
            migration_info = {
                "needs_migration": True,
                "migration_type": "grandfathered",
                "current_access": "full",
                "grace_period_end": user_info["grace_period_end"],
                "days_left": user_info["days_left"]
            }
        
        return JSONResponse(content={
            "success": True,
            "migration_info": migration_info
        })
        
    except Exception as e:
        logger.error(f"Error fetching migration status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch migration status")

@router.get("/billing-history")
async def get_billing_history(
    current_user: User = Depends(get_current_user)
):
    """Get user's billing history"""
    try:
        # Get user's subscription transactions
        result = supabase.table("subscription_transactions").select("*").eq("user_id", current_user.id).order("created_at", desc=True).execute()
        
        billing_history = []
        for transaction in result.data:
            # Get plan details for display
            plan_result = supabase.table("subscription_plans").select("display_name").eq("name", transaction.get("subscription_plan", "starter")).execute()
            plan_name = plan_result.data[0]["display_name"] if plan_result.data else "Unknown Plan"
            
            billing_history.append({
                "id": transaction.get("razorpay_payment_id", f"txn_{transaction['id']}"),
                "date": transaction.get("created_at", ""),
                "amount": transaction.get("amount", 0),
                "status": transaction.get("status", "completed"),
                "description": f"{plan_name} - Payment",
                "currency": transaction.get("currency", "INR"),
                "payment_method": transaction.get("payment_method", "card")
            })
        
        return JSONResponse(content={
            "success": True,
            "billing_history": billing_history
        })
        
    except Exception as e:
        logger.error(f"Error fetching billing history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch billing history")

@router.post("/cancel")
async def cancel_subscription(
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user)
):
    """Cancel user's subscription"""
    try:
        subscription_id = request.get("subscription_id")
        
        if not subscription_id:
            raise HTTPException(status_code=400, detail="Subscription ID is required")
        
        # Update subscription status to cancelled
        result = supabase.table("profiles").update({
            "subscription_status": "cancelled",
            "subscription_end_date": datetime.utcnow().isoformat()
        }).eq("id", current_user.id).eq("razorpay_subscription_id", subscription_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        logger.info(f"Subscription cancelled for user {current_user.id}")
        
        return JSONResponse(content={
            "success": True,
            "message": "Subscription cancelled successfully"
        })
        
    except Exception as e:
        logger.error(f"Error cancelling subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")

@router.post("/create")
async def create_subscription(
    request: SubscriptionCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """Create a new subscription"""
    try:
        logger.info(f"Creating subscription for user {current_user.id}, plan: {request.plan_name}, billing: {request.billing_cycle}")
        
        # Check if user already has active subscription
        result = supabase.rpc("get_user_subscription_info", {"user_uuid": current_user.id}).execute()
        
        # Also get subscription_end_date directly from profile
        profile_result = supabase.table("profiles").select("subscription_status, subscription_plan, subscription_end_date").eq("id", current_user.id).execute()
        subscription_end_date = None
        if profile_result.data:
            subscription_end_date = profile_result.data[0].get("subscription_end_date")
            current_plan = profile_result.data[0].get("subscription_plan", "")
            current_status = profile_result.data[0].get("subscription_status", "")
        else:
            current_plan = ""
            current_status = ""
        
        # Check if subscription has actually expired (end_date in the past)
        is_subscription_expired = False
        if subscription_end_date:
            from datetime import datetime
            try:
                if isinstance(subscription_end_date, str):
                    end_date = datetime.fromisoformat(subscription_end_date.replace('Z', '+00:00'))
                else:
                    end_date = subscription_end_date
                from datetime import timezone
                now = datetime.now(timezone.utc) if end_date.tzinfo else datetime.utcnow()
                if end_date.tzinfo:
                    now = now.replace(tzinfo=timezone.utc)
                else:
                    end_date = end_date.replace(tzinfo=None)
                    now = now.replace(tzinfo=None)
                is_subscription_expired = end_date < now
                logger.info(f"User {current_user.id} subscription_end_date: {subscription_end_date}, is_expired: {is_subscription_expired}")
            except Exception as e:
                logger.warning(f"Error parsing subscription_end_date: {e}")
        
        has_active_subscription = result.data and result.data[0].get("has_active_subscription", False)
        
        # If subscription has expired, allow renewal/upgrade regardless of status
        if is_subscription_expired:
            logger.info(f"User {current_user.id} subscription has expired, allowing renewal/upgrade to {request.plan_name}")
            # Continue with subscription creation - will renew/upgrade
        elif has_active_subscription:
            # Allow upgrading from trial to paid plans or changing between paid plans
            # If user is trying to activate free trial again, block it
            if request.plan_name == "free_trial":
                logger.warning(f"User {current_user.id} already has active subscription, cannot activate free trial again")
                raise HTTPException(status_code=400, detail="You already have an active subscription. Please upgrade to a paid plan.")
            
            # If user is on trial and trying to upgrade to paid plan, allow it
            if current_status == "trial" and request.plan_name != "free_trial":
                logger.info(f"User {current_user.id} upgrading from trial to {request.plan_name}, allowing upgrade")
                # Continue with subscription creation - will update subscription
            elif current_status == "active" and current_plan != request.plan_name:
                # User is upgrading/downgrading between paid plans - allow it
                logger.info(f"User {current_user.id} changing plan from {current_plan} to {request.plan_name}, allowing change")
                # Continue with subscription creation - will update subscription
            elif current_plan == request.plan_name:
                # User already has the same plan and it's still active - allow renewal if they want to extend
                logger.info(f"User {current_user.id} renewing/extending plan {current_plan}, allowing renewal")
                # Continue with subscription creation - will extend subscription
            else:
                # Other cases - allow upgrade/change
                logger.info(f"User {current_user.id} has {current_status} status with plan {current_plan}, allowing change to {request.plan_name}")
                # Continue with subscription creation
        
        # Get plan details
        plan_result = supabase.table("subscription_plans").select("*").eq("name", request.plan_name).eq("is_active", True).execute()
        
        if not plan_result.data:
            logger.error(f"Plan not found: {request.plan_name}")
            raise HTTPException(status_code=404, detail="Plan not found")
        
        plan = plan_result.data[0]
        logger.info(f"Found plan: {plan['name']}, monthly price: {plan['price_monthly']}, yearly price: {plan['price_yearly']}")
        
        # Handle free trial differently - no Razorpay needed
        if request.plan_name == "free_trial":
            logger.info(f"Handling free trial activation for user {current_user.id}")
            
            # Ensure profile exists
            profile_check = supabase.table("profiles").select("id").eq("id", current_user.id).execute()
            
            if not profile_check.data:
                # Create basic profile if it doesn't exist
                logger.info(f"Creating profile for user {current_user.id}")
                supabase.table("profiles").insert({
                    "id": current_user.id,
                    "name": current_user.name,
                    "onboarding_completed": False,
                    "subscription_status": "trial",
                    "migration_status": "trial_user"
                }).execute()
                logger.info(f"Profile created for user {current_user.id}")
            
            # Update user profile with trial info
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            trial_end = now + timedelta(days=3)
            
            logger.info(f"Activating trial for user {current_user.id}")
            supabase.table("profiles").update({
                "subscription_plan": "free_trial",
                "subscription_status": "trial",
                "subscription_start_date": now.isoformat(),
                "subscription_end_date": trial_end.isoformat(),
                "trial_activated_at": now.isoformat(),
                "trial_expires_at": trial_end.isoformat(),
                "has_had_trial": True,
                "migration_status": "trial_user"
            }).eq("id", current_user.id).execute()
            
            return JSONResponse(content={
                "success": True,
                "subscription_id": f"trial_{current_user.id[:8]}",
                "customer_id": None,
                "payment_url": None,
                "message": "Free trial activated successfully"
            })
        
        # Handle paid plans with Razorpay
        logger.info(f"Handling paid plan subscription for user {current_user.id}")
        
        # Create Razorpay customer
        logger.info(f"Creating Razorpay customer for user {current_user.id}")
        customer_id = await razorpay_service.create_customer({
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email
        })
        logger.info(f"Created Razorpay customer: {customer_id}")
        
        # Generate a unique subscription ID for tracking
        import uuid
        subscription_id = f"sub_{uuid.uuid4().hex[:8]}"
        logger.info(f"Generated subscription ID: {subscription_id}")
        
        # Ensure profile exists before updating subscription info
        logger.info(f"Ensuring profile exists for user {current_user.id}")
        
        # First check if profile exists
        profile_check = supabase.table("profiles").select("id").eq("id", current_user.id).execute()
        
        if not profile_check.data:
            # Create basic profile if it doesn't exist
            logger.info(f"Creating profile for user {current_user.id}")
            supabase.table("profiles").insert({
                "id": current_user.id,
                "name": current_user.name,
                "onboarding_completed": False,
                "subscription_status": "inactive",
                "migration_status": "pending"
            }).execute()
            logger.info(f"Profile created for user {current_user.id}")
        
        # Update user profile with subscription info
        logger.info(f"Updating user profile with subscription info")
        supabase.table("profiles").update({
            "razorpay_customer_id": customer_id,
            "razorpay_subscription_id": subscription_id,
            "subscription_plan": request.plan_name,
            "migration_status": 'migrated'
        }).eq("id", current_user.id).execute()
        
        # Create payment link
        amount = plan["price_monthly"] if request.billing_cycle == "monthly" else plan["price_yearly"]
        logger.info(f"Creating payment link for amount: {amount}")
        payment_url = await razorpay_service.create_payment_link(
            subscription_id, 
            amount,
            customer_name=current_user.name,
            customer_email=current_user.email
        )
        logger.info(f"Created payment link: {payment_url}")
        
        return JSONResponse(content={
            "success": True,
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "payment_url": payment_url,
            "message": "Subscription created successfully"
        })
        
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to create subscription: {str(e)}")

@router.post("/webhook")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhooks"""
    try:
        # Parse webhook data
        webhook_data = await request.json()
        event_type = webhook_data.get("event")
        
        logger.info(f"Webhook received - Event: {event_type}")
        
        # Process webhook based on event type
        if event_type == "subscription.activated":
            await _handle_subscription_activated(webhook_data)
        elif event_type == "subscription.charged":
            await _handle_subscription_charged(webhook_data)
        elif event_type == "subscription.cancelled":
            await _handle_subscription_cancelled(webhook_data)
        elif event_type == "subscription.completed":
            await _handle_subscription_completed(webhook_data)
        elif event_type == "subscription.paused":
            await _handle_subscription_paused(webhook_data)
        elif event_type == "subscription.resumed":
            await _handle_subscription_resumed(webhook_data)
        elif event_type == "payment_link.paid":
            await _handle_payment_link_paid(webhook_data)
        else:
            logger.warning(f"Unhandled webhook event: {event_type}")
        
        return JSONResponse(content={"success": True, "event": event_type})
        
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

async def _handle_subscription_activated(webhook_data: Dict[str, Any]):
    """Handle subscription activated webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription.get("id")
    
    if subscription_id:
        # Activate subscription in database
        supabase.table("profiles").update({
            "subscription_status": 'active',
            "subscription_start_date": datetime.utcnow().isoformat(),
            "subscription_end_date": (datetime.utcnow() + timedelta(days=30)).isoformat()
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_subscription_charged(webhook_data: Dict[str, Any]):
    """Handle subscription charged webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    payment = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
    
    subscription_id = subscription.get("id")
    payment_id = payment.get("id")
    
    if subscription_id and payment_id:
        # Record successful payment
        supabase.table("subscription_transactions").insert({
            "subscription_id": subscription_id,
            "razorpay_payment_id": payment_id,
            "amount": payment.get("amount", 0),
            "status": 'completed'
        }).execute()
        
        # Update subscription end date
        supabase.table("profiles").update({
            "subscription_end_date": (datetime.utcnow() + timedelta(days=30)).isoformat()
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_subscription_cancelled(webhook_data: Dict[str, Any]):
    """Handle subscription cancelled webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription.get("id")
    
    if subscription_id:
        # Cancel subscription in database
        supabase.table("profiles").update({
            "subscription_status": 'cancelled',
            "subscription_end_date": datetime.utcnow().isoformat()
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_subscription_completed(webhook_data: Dict[str, Any]):
    """Handle subscription completed webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription.get("id")
    
    if subscription_id:
        # Mark subscription as completed
        supabase.table("profiles").update({
            "subscription_status": 'completed'
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_subscription_paused(webhook_data: Dict[str, Any]):
    """Handle subscription paused webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription.get("id")
    
    if subscription_id:
        # Pause subscription in database
        supabase.table("profiles").update({
            "subscription_status": 'paused'
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_subscription_resumed(webhook_data: Dict[str, Any]):
    """Handle subscription resumed webhook"""
    subscription = webhook_data.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = subscription.get("id")
    
    if subscription_id:
        # Resume subscription in database
        supabase.table("profiles").update({
            "subscription_status": 'active'
        }).eq("razorpay_subscription_id", subscription_id).execute()

async def _handle_payment_link_paid(webhook_data: Dict[str, Any]):
    """Handle payment link paid webhook"""
    payment_link = webhook_data.get("payload", {}).get("payment_link", {}).get("entity", {})
    payment = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
    
    payment_link_id = payment_link.get("id")
    payment_id = payment.get("id")
    amount = payment.get("amount", 0)
    
    logger.info(f"Payment link paid: {payment_link_id}, Payment: {payment_id}, Amount: {amount}")
    
    if payment_link_id and payment_id:
        # Find user by payment link reference (subscription ID)
        # The payment link description contains the subscription ID
        description = payment_link.get("description", "")
        subscription_id = None
        
        # Extract subscription ID from description
        if "Subscription payment for" in description:
            subscription_id = description.replace("Subscription payment for ", "").strip()
        
        if subscription_id:
            # Use service role key for admin access
            from supabase import create_client
            import os
            
            supabase_admin = create_client(
                os.getenv("SUPABASE_URL"),
                os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            )
            
            # Find user with this subscription ID
            user_result = supabase_admin.table("profiles").select("id, subscription_plan").eq("razorpay_subscription_id", subscription_id).execute()
            
            if user_result.data:
                user = user_result.data[0]
                user_id = user["id"]
                plan = user.get("subscription_plan", "starter")
                
                # Validate payment amount matches expected plan price
                plan_result = supabase_admin.table("subscription_plans").select("price_monthly, price_yearly").eq("name", plan).execute()
                
                if plan_result.data:
                    expected_amount = plan_result.data[0]["price_monthly"]  # Assuming monthly for now
                    
                    # Validate payment amount
                    if amount != expected_amount:
                        logger.warning(f"Payment amount {amount} does not match expected amount {expected_amount} for plan {plan}")
                        return
                
                # Ensure profile exists before updating subscription status
                profile_check = supabase_admin.table("profiles").select("id").eq("id", user_id).execute()
                
                if not profile_check.data:
                    # Create basic profile if it doesn't exist
                    logger.info(f"Creating profile for user {user_id} during webhook")
                    supabase_admin.table("profiles").insert({
                        "id": user_id,
                        "name": "User",  # Default name since we don't have user details in webhook
                        "onboarding_completed": False,
                        "subscription_status": "inactive",
                        "migration_status": "pending"
                    }).execute()
                    logger.info(f"Profile created for user {user_id}")
                
                # Activate subscription
                now = datetime.utcnow()
                end_date = now + timedelta(days=30)
                
                update_result = supabase_admin.table("profiles").update({
                    "subscription_status": "active",
                    "subscription_start_date": now.isoformat(),
                    "subscription_end_date": end_date.isoformat(),
                    "migration_status": "migrated"
                }).eq("id", user_id).execute()
                
                if update_result.data:
                    # Record payment transaction
                    supabase_admin.table("subscription_transactions").insert({
                        "user_id": user_id,
                        "subscription_id": subscription_id,
                        "razorpay_payment_id": payment_id,
                        "amount": amount,
                        "currency": "INR",
                        "status": "completed",
                        "payment_method": payment.get("method", "card")
                    }).execute()
                    
                    logger.info(f"Subscription activated for user {user_id} with plan {plan}")
                else:
                    logger.error(f"Failed to update user profile for user {user_id}")
            else:
                logger.warning(f"No user found with subscription ID: {subscription_id}")
        else:
            logger.warning(f"Could not extract subscription ID from description: {description}")
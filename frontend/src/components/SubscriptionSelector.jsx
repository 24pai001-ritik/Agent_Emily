import React, { useState, useEffect } from 'react';
import { Check, ArrowRight, Loader2, Home, HelpCircle, Settings, LogOut, Clock, Gift } from 'lucide-react';
import { subscriptionAPI } from '../services/subscription';
import { trialAPI } from '../services/trial';
import { onboardingAPI } from '../services/onboarding';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';

const SubscriptionSelector = () => {
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [billingCycle, setBillingCycle] = useState('monthly');
  const [loadingPlans, setLoadingPlans] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(null); // Track which plan is loading
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [trialInfo, setTrialInfo] = useState(null);
  const [loadingTrial, setLoadingTrial] = useState(true);
  const [subscriptionStatus, setSubscriptionStatus] = useState(null);
  const [countdown, setCountdown] = useState(null);
  const { logout } = useAuth();

  // Function to fetch subscription data
  const fetchSubscriptionData = async () => {
      try {
        // Fetch subscription plans
        const plansResponse = await subscriptionAPI.getPlans();
      const plansData = plansResponse?.data?.plans || plansResponse?.plans || [];
      console.log('Plans fetched:', plansData);
      setPlans(Array.isArray(plansData) ? plansData : []);
        setLoadingPlans(false);

        // Fetch trial information
        try {
          const trialResponse = await trialAPI.getTrialInfo();
        const trialData = trialResponse?.data?.trial_info || trialResponse?.trial_info;
        console.log('Trial info fetched:', trialData);
        setTrialInfo(trialData || null);
        } catch (trialError) {
          console.log('No trial information available:', trialError);
          setTrialInfo(null);
        }

      // Fetch subscription status to check if user has active subscription
      try {
        const statusResponse = await subscriptionAPI.getSubscriptionStatus();
        console.log('Subscription status fetched:', statusResponse.data);
        setSubscriptionStatus(statusResponse.data);
      } catch (statusError) {
        console.log('No subscription status available:', statusError);
        setSubscriptionStatus(null);
      }
      } catch (error) {
        console.error('Error fetching subscription plans:', error);
      setPlans([]); // Ensure plans is always an array
        setLoadingPlans(false);
      } finally {
        setLoadingTrial(false);
      }
    };

  useEffect(() => {
    fetchSubscriptionData();
    
    // Check if user is returning from payment (check URL parameters)
    const urlParams = new URLSearchParams(window.location.search);
    const paymentSuccess = urlParams.get('payment_success');
    const paymentFailed = urlParams.get('payment_failed');
    
    if (paymentSuccess === 'true') {
      console.log('Payment successful, refreshing subscription status...');
      // Wait a moment for webhook to process, then refresh
      setTimeout(() => {
        fetchSubscriptionData();
      }, 2000);
      // Clean up URL parameter
      window.history.replaceState({}, '', window.location.pathname);
    } else if (paymentFailed === 'true') {
      console.log('Payment failed');
      // Clean up URL parameter
      window.history.replaceState({}, '', window.location.pathname);
    }
    
    // Also refresh when page becomes visible (user returns from payment page)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        console.log('Page visible, refreshing subscription status...');
        setTimeout(() => {
          fetchSubscriptionData();
        }, 1000);
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    // Periodically refresh subscription status to catch backend updates
    // This ensures the UI reflects status changes (e.g., expired -> active when date hasn't passed)
    const statusRefreshInterval = setInterval(() => {
      console.log('Periodically refreshing subscription status...');
      fetchSubscriptionData();
    }, 10000); // Refresh every 10 seconds
    
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      clearInterval(statusRefreshInterval);
    };
  }, []);

  // Countdown timer effect for active trial - calculate from trial_expires_at or trial_end
  // Only show countdown if has_had_trial is true (user actually activated the trial)
  useEffect(() => {
    // Use trial_expires_at first, fallback to trial_end
    const expirationDate = trialInfo?.trial_expires_at || trialInfo?.trial_end;
    
    // Only set up countdown if:
    // 1. User has activated trial (has_had_trial === true)
    // 2. Expiration date exists
    if (expirationDate && trialInfo?.has_had_trial === true) {
      console.log('Setting up countdown timer for expiration date:', expirationDate, 'has_had_trial:', trialInfo.has_had_trial);
      const updateCountdown = () => {
        try {
          const now = new Date();
          let expiresAt;
          
          // Handle timezone issues - try multiple formats
          const expiresAtStr = expirationDate;
          if (typeof expiresAtStr === 'string') {
            // Try parsing as-is first
            expiresAt = new Date(expiresAtStr);
            
            // If invalid, try adding Z for UTC
            if (isNaN(expiresAt.getTime())) {
              expiresAt = new Date(expiresAtStr + 'Z');
            }
          } else {
            expiresAt = new Date(expiresAtStr);
          }
          
          // Check if date is valid
          if (isNaN(expiresAt.getTime())) {
            console.error('Invalid expiration date:', expirationDate);
            setCountdown(null);
            return;
          }
          
          const diff = expiresAt - now;
          console.log('Countdown diff:', diff, 'expiresAt:', expiresAt, 'now:', now);

          if (diff > 0) {
            const days = Math.floor(diff / (1000 * 60 * 60 * 24));
            const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const seconds = Math.floor((diff % (1000 * 60)) / 1000);

            const countdownValue = { days, hours, minutes, seconds };
            console.log('Setting countdown:', countdownValue);
            setCountdown(countdownValue);
          } else {
            console.log('Trial expired, setting countdown to 0');
            setCountdown({ days: 0, hours: 0, minutes: 0, seconds: 0 });
          }
        } catch (error) {
          console.error('Error calculating countdown:', error, trialInfo);
          setCountdown(null);
        }
      };

      updateCountdown();
      const interval = setInterval(updateCountdown, 1000);

      return () => clearInterval(interval);
    } else {
      if (!expirationDate) {
        console.log('No expiration date (trial_expires_at or trial_end), clearing countdown');
      } else if (trialInfo?.has_had_trial !== true) {
        console.log('has_had_trial is not true, clearing countdown. has_had_trial:', trialInfo?.has_had_trial);
      }
      setCountdown(null);
    }
  }, [trialInfo?.trial_expires_at, trialInfo?.trial_end, trialInfo?.has_had_trial]);

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setIsLoggingOut(false);
    }
  };

  const handleSubscribe = async (planName) => {
    setLoadingPlan(planName);
    try {
      console.log('🚀 Creating subscription for plan:', planName, 'billing:', billingCycle);
      
      // First ensure profile exists
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          console.log('🔍 Ensuring profile exists before subscription creation...');
          
          // Check if profile exists
          const { data: existingProfile } = await supabase
            .from('profiles')
            .select('id')
            .eq('id', user.id)
            .maybeSingle();
          
          if (!existingProfile) {
            console.log('➕ Creating profile before subscription...');
            await supabase
              .from('profiles')
              .upsert({
                id: user.id,
                name: user.user_metadata?.name || user.email,
                onboarding_completed: false,
                subscription_status: 'inactive',
                migration_status: 'pending'
              });
            console.log('✅ Profile created successfully!');
          }
        }
      } catch (profileError) {
        console.log('⚠️ Profile creation failed, proceeding anyway:', profileError);
      }
      
      const response = await subscriptionAPI.createSubscription({
        plan_name: planName,
        billing_cycle: billingCycle
      });
      
      console.log('📊 Subscription creation response:', response.data);
      
      if (response.data.success) {
        if (response.data.payment_url) {
          console.log('✅ Payment URL received, redirecting to:', response.data.payment_url);
          // Redirect to Razorpay payment page for paid plans
          window.location.href = response.data.payment_url;
        } else if (planName === 'free_trial') {
          console.log('✅ Free trial activated successfully!');
          // Free trial - check onboarding and redirect accordingly
          // Add a small delay to ensure subscription is saved
          await new Promise(resolve => setTimeout(resolve, 500));
          
          try {
            const onboardingResponse = await onboardingAPI.getOnboardingStatus();
            console.log('📋 Onboarding status response:', onboardingResponse);
            console.log('📋 Onboarding completed value:', onboardingResponse?.data?.onboarding_completed);
            
            if (onboardingResponse?.data?.onboarding_completed === true) {
              // Onboarding complete - go to dashboard
              console.log('🎯 Onboarding complete, redirecting to dashboard');
              window.location.href = '/dashboard';
        } else {
              // Onboarding incomplete - go to onboarding
              console.log('📝 Onboarding incomplete, redirecting to onboarding');
              window.location.href = '/onboarding';
            }
          } catch (error) {
            console.error('Error checking onboarding status:', error);
            console.error('Error details:', error.response?.data || error.message);
            // Default to onboarding if check fails
            console.log('⚠️ Defaulting to onboarding due to error');
            window.location.href = '/onboarding';
          }
        }
      } else {
        console.error('❌ Failed to create subscription');
        console.error('Response data:', response.data);
        alert(`Failed to create subscription: ${response.data.message || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('💥 Error creating subscription:', error);
      console.error('Error details:', error.response?.data);
      alert(`Error creating subscription: ${error.response?.data?.detail || error.message || 'Unknown error'}`);
    } finally {
      setLoadingPlan(null);
    }
  };

  if (loadingPlans || loadingTrial) {
    return (
      <div className="min-h-screen bg-[#F6F6F6] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-[#9E005C]" />
          <p className="text-gray-600">Loading subscription plans...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F6F6F6] flex flex-col">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 sm:py-4">
          <div className="flex items-center justify-between">
            {/* Logo and Brand */}
            <div className="flex items-center space-x-2 sm:space-x-4">
              <div className="w-8 h-8 sm:w-12 sm:h-12 bg-gradient-to-r from-pink-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg">
                <span className="text-white font-bold text-sm sm:text-xl">E</span>
              </div>
              <div>
                <h1 className="text-lg sm:text-2xl font-bold text-gray-900">Emily</h1>
                <p className="text-xs sm:text-sm text-gray-500 hidden sm:block">AI Marketing Assistant</p>
              </div>
            </div>

            {/* Header Buttons - Desktop */}
            <div className="hidden md:flex items-center space-x-3">
              <button
                onClick={() => window.location.href = '/dashboard'}
                className="flex items-center space-x-2 px-4 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <Home className="w-4 h-4" />
                <span className="text-sm font-medium">Dashboard</span>
              </button>
              
              <button
                onClick={() => window.open('/help', '_blank')}
                className="flex items-center space-x-2 px-4 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <HelpCircle className="w-4 h-4" />
                <span className="text-sm font-medium">Help</span>
              </button>
              
              <button
                onClick={() => window.location.href = '/profile'}
                className="flex items-center space-x-2 px-4 py-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <Settings className="w-4 h-4" />
                <span className="text-sm font-medium">Settings</span>
              </button>
              
              <div className="h-6 w-px bg-gray-300"></div>
              
              <button
                onClick={handleLogout}
                disabled={isLoggingOut}
                className="flex items-center space-x-2 px-4 py-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoggingOut ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <LogOut className="w-4 h-4" />
                )}
                <span className="text-sm font-medium">
                  {isLoggingOut ? 'Logging out...' : 'Logout'}
                </span>
              </button>
            </div>

            {/* Mobile Header Buttons */}
            <div className="flex md:hidden items-center space-x-2">
              <button
                onClick={() => window.location.href = '/dashboard'}
                className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                title="Dashboard"
              >
                <Home className="w-5 h-5" />
              </button>
              
              <button
                onClick={() => window.open('/help', '_blank')}
                className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                title="Help"
              >
                <HelpCircle className="w-5 h-5" />
              </button>
              
              <button
                onClick={() => window.location.href = '/profile'}
                className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                title="Settings"
              >
                <Settings className="w-5 h-5" />
              </button>
              
              <div className="h-6 w-px bg-gray-300"></div>
              
              <button
                onClick={handleLogout}
                disabled={isLoggingOut}
                className="p-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Logout"
              >
                {isLoggingOut ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <LogOut className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex items-center justify-center py-4 sm:py-8">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 w-full">
        {/* Header */}
        <div className="text-center mb-6 sm:mb-8">
          <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-3 sm:mb-4">
            <span className="bg-gradient-to-r from-[#9E005C] to-[#FF4D94] bg-clip-text text-transparent">
              Choose Your Plan
            </span>
          </h1>
          <p className="text-base sm:text-lg text-gray-600 mb-4 sm:mb-6 px-4 sm:px-0">
            Select a subscription plan to continue with your Emily setup
          </p>
          
          {/* Billing Cycle Toggle */}
          <div className="flex items-center justify-center space-x-3 sm:space-x-4 mb-4 sm:mb-6">
            <span className={`text-sm font-medium ${billingCycle === 'monthly' ? 'text-[#9E005C]' : 'text-gray-500'}`}>
              Monthly
            </span>
            <button
              onClick={() => setBillingCycle(billingCycle === 'monthly' ? 'yearly' : 'monthly')}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                billingCycle === 'yearly' ? 'bg-[#9E005C]' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  billingCycle === 'yearly' ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
            <span className={`text-sm font-medium ${billingCycle === 'yearly' ? 'text-[#9E005C]' : 'text-gray-500'}`}>
              Yearly
            </span>
            {billingCycle === 'yearly' && (
              <span className="bg-green-100 text-green-800 text-xs font-medium px-2 py-1 rounded-full">
                Save 17%
              </span>
            )}
          </div>
        </div>

        {/* Plans Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6 max-w-6xl mx-auto">
          {plans && Array.isArray(plans) && plans.length > 0 ? (
            plans
            .sort((a, b) => {
              // Define the order: trial, basic, pro
              const order = { 'free_trial': 0, 'starter': 1, 'basic': 1, 'pro': 2 };
              const aOrder = order[a.name] ?? 999;
              const bOrder = order[b.name] ?? 999;
              return aOrder - bOrder;
            })
            .map((plan) => {
            const isFreeTrial = plan.name === 'free_trial';
            const price = billingCycle === 'monthly' ? plan.price_monthly : plan.price_yearly;
            const isPro = plan.name === 'pro';
            
            // Get expiration date for trial
            const expirationDate = trialInfo?.trial_expires_at || trialInfo?.trial_end;
            
            // Get subscription end date for paid plans
            const subscriptionEndDate = subscriptionStatus?.subscription_end_date;
            // Trim whitespace from plan name to handle trailing spaces from backend
            const currentPlan = subscriptionStatus?.plan ? subscriptionStatus.plan.trim() : null;
            const subscriptionStatusValue = subscriptionStatus?.status;
            
            // Check if this is the user's current paid plan (monthly/yearly, not trial)
            // Plan names are stored as "starter", "pro", etc. (without _monthly/_yearly suffix)
            // Make comparison case-insensitive to handle "Starter" vs "starter"
            // Also trim to handle trailing spaces
            const currentPlanLower = currentPlan ? currentPlan.toLowerCase().trim() : '';
            const planNameLower = plan.name ? plan.name.toLowerCase().trim() : '';
            const isCurrentPaidPlan = !isFreeTrial && currentPlan && 
                                     (currentPlanLower === planNameLower || 
                                      currentPlanLower.startsWith(planNameLower + '_') ||
                                      planNameLower === currentPlanLower);
            
            // Debug logging
            if (currentPlan) {
              console.log(`Plan matching: currentPlan="${currentPlan}", plan.name="${plan.name}", isCurrentPaidPlan=${isCurrentPaidPlan}`);
            }
            
            // Check if paid plan has expired - check date directly, not just status
            // A plan is expired ONLY if the subscription_end_date has actually passed
            const subscriptionEndDateObj = subscriptionEndDate ? new Date(subscriptionEndDate) : null;
            const now = new Date();
            const hasEndDatePassed = subscriptionEndDateObj && subscriptionEndDateObj <= now;
            
            // Plan is expired if: it's the current plan AND end date has passed
            const isPaidPlanExpired = isCurrentPaidPlan && hasEndDatePassed;
            
            // Check if trial has expired
            // Trial is expired ONLY if:
            // 1. has_had_trial === true (user actually used the trial), AND
            // 2. trial_end_date (trial_expires_at or trial_end) exists and has passed
            // If has_had_trial === false, trial is NOT expired (it's available to use)
            const isTrialExpired = isFreeTrial && trialInfo && 
                                   trialInfo.has_had_trial === true && 
                                   expirationDate && 
                                   new Date(expirationDate) <= new Date();
            
            // Check if user has an active trial
            // Show countdown if: has_had_trial === true AND trial hasn't expired AND expiration date exists
            const hasActiveTrial = isFreeTrial && 
                                   trialInfo && 
                                   trialInfo.has_had_trial === true && 
                                   expirationDate && 
                                   new Date(expirationDate) > new Date() &&
                                   !isTrialExpired;
            
            // Check if user already has active subscription (for paid plans)
            // Consider active if: has_active_subscription is true OR status is 'active' OR end date hasn't passed
            const hasActiveSubscription = subscriptionStatus?.has_active_subscription || 
                                         (trialInfo?.subscription_status === 'active') ||
                                         (isCurrentPaidPlan && subscriptionEndDateObj && subscriptionEndDateObj > now);
            
            // Check if user has this paid plan active (not expired)
            // Plan is active if: it's the current plan AND (has_active_subscription OR end date hasn't passed OR status is 'active')
            const isPaidPlanActive = isCurrentPaidPlan && 
                                    (subscriptionStatus?.has_active_subscription || 
                                     (subscriptionEndDateObj && subscriptionEndDateObj > now) ||
                                     subscriptionStatusValue === 'active') && 
                                    !isPaidPlanExpired;
            
            // Debug logging for active plan check
            if (isCurrentPaidPlan) {
              console.log(`Active plan check: isCurrentPaidPlan=${isCurrentPaidPlan}, has_active_subscription=${subscriptionStatus?.has_active_subscription}, endDatePassed=${hasEndDatePassed}, status=${subscriptionStatusValue}, isPaidPlanActive=${isPaidPlanActive}`);
            }
            
            // Disable free trial card if user already has active trial/subscription
            // Show as active ONLY if has_had_trial is true AND trial hasn't expired
            const isTrialAlreadyActive = hasActiveTrial || (isFreeTrial && trialInfo?.has_had_trial === true && hasActiveSubscription && !isTrialExpired);
            
            // Dynamically update display name based on billing cycle
            const getDisplayName = () => {
              if (isFreeTrial) {
                return plan.display_name; // Free Trial doesn't change
              }
              // Replace "Monthly" with "Yearly" or vice versa based on billing cycle
              if (billingCycle === 'yearly') {
                return plan.display_name.replace(/Monthly/gi, 'Yearly');
              } else {
                return plan.display_name.replace(/Yearly/gi, 'Monthly');
              }
            };
            
            // Format price display - special handling for Free Trial
            const getPriceDisplay = () => {
              if (isFreeTrial) {
                return {
                  price: 'for 3 days',
                  period: null
                };
              }
              return {
                price: `₹${(price / 100).toFixed(0)}`,
                period: billingCycle === 'monthly' ? 'month' : 'year'
              };
            };
            
            const displayName = getDisplayName();
            const priceInfo = getPriceDisplay();
            
            return (
              <div
                key={plan.id}
                className={`relative rounded-xl p-4 sm:p-6 border transition-all duration-300 ${
                  isTrialExpired
                    ? 'bg-gray-100 border-gray-300 grayscale opacity-75 cursor-not-allowed'
                    : isPaidPlanExpired
                    ? 'bg-white border-gray-300 hover:border-[#FF4D94] hover:shadow-lg'
                    : isTrialAlreadyActive || isPaidPlanActive
                    ? 'bg-gradient-to-br from-pink-50 to-purple-50 border-[#FF4D94] shadow-md'
                    : isPro 
                    ? 'bg-white border-[#FF4D94] shadow-lg hover:shadow-xl' 
                    : 'bg-white border-gray-200 hover:border-[#9E005C] hover:shadow-lg'
                }`}
              >
                {/* Show badges in priority order: Current Plan > Expired > Active Trial > Most Popular */}
                {isPaidPlanActive && !isPaidPlanExpired && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <div className="bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white px-3 py-1 rounded-full text-xs font-medium shadow-lg">
                      Current Plan
                    </div>
                  </div>
                )}
                
                {isTrialExpired && !isPaidPlanActive && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <div className="bg-gray-500 text-white px-3 py-1 rounded-full text-xs font-medium">
                      Trial Expired
                    </div>
                  </div>
                )}
                
                {isPaidPlanExpired && !isPaidPlanActive && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <div className="bg-gray-500 text-white px-3 py-1 rounded-full text-xs font-medium">
                      Plan Expired
                    </div>
                  </div>
                )}
                
                {isTrialAlreadyActive && !isPaidPlanActive && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <div className="bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white px-3 py-1 rounded-full text-xs font-medium shadow-lg">
                      Trial Active
                    </div>
                  </div>
                )}
                
                {/* Show "Most Popular" only if pro plan is not active */}
                {isPro && !isPaidPlanActive && (
                  <div className="absolute -top-3 left-1/2 transform -translate-x-1/2">
                    <div className="bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white px-3 py-1 rounded-full text-xs font-medium">
                      Most Popular
                    </div>
                  </div>
                )}
                
                <div className="text-center mb-4 sm:mb-6">
                  <h3 className={`text-lg sm:text-xl font-bold mb-2 ${isTrialExpired || isPaidPlanExpired ? 'text-gray-500' : isTrialAlreadyActive || isPaidPlanActive ? 'text-gray-900' : 'text-gray-900'}`}>
                    {displayName}
                  </h3>
                  {isTrialExpired ? (
                    <div className="text-base sm:text-lg font-semibold text-gray-500 mb-2">
                      Your trial is expired
                    </div>
                  ) : isPaidPlanExpired ? (
                    <div className="text-base sm:text-lg font-semibold text-gray-500 mb-2">
                      Your plan is expired please upgrade your plan or renewal your plan
                    </div>
                  ) : isTrialAlreadyActive ? (
                    <div className="space-y-2">
                      <div className="text-base sm:text-lg font-semibold bg-gradient-to-r from-[#FF4D94] to-[#9E005C] bg-clip-text text-transparent mb-2">
                        Your trial is active
                      </div>
                      {(trialInfo?.trial_expires_at || trialInfo?.trial_end) && (
                        <div className="text-xs text-gray-500 mt-1">
                          Expires: {new Date(trialInfo.trial_expires_at || trialInfo.trial_end).toLocaleDateString('en-US', { 
                            month: 'short', 
                            day: 'numeric', 
                            year: 'numeric' 
                          })}
                        </div>
                      )}
                    </div>
                  ) : (
                  <div className="text-2xl sm:text-3xl font-bold mb-1">
                    <span className={`${isPro ? 'text-[#FF4D94]' : 'text-[#9E005C]'}`}>
                      {priceInfo.price}
                    </span>
                    {priceInfo.period && (
                      <span className="text-gray-500 text-sm sm:text-base">/{priceInfo.period}</span>
                    )}
                  </div>
                  )}
                </div>
                
                <div className="space-y-2 sm:space-y-3 mb-4 sm:mb-6">
                  {(() => {
                    // Handle different feature structures
                    let featuresArray = [];
                    
                    if (Array.isArray(plan.features)) {
                      featuresArray = plan.features;
                    } else if (typeof plan.features === 'object' && plan.features !== null) {
                      if (plan.features.features && Array.isArray(plan.features.features)) {
                        featuresArray = plan.features.features;
                      } else if (plan.features.trial !== undefined) {
                        // Handle nested object structure
                        featuresArray = plan.features.features || [];
                      }
                    } else if (typeof plan.features === 'string') {
                      featuresArray = [plan.features];
                    }
                    
                    // Ensure we have a valid array
                    if (!Array.isArray(featuresArray)) {
                      featuresArray = [];
                    }
                    
                    // Helper function to format feature text
                    const formatFeature = (text) => {
                      if (typeof text !== 'string') return text;
                      // Replace underscores with spaces and capitalize each word
                      return text
                        .replace(/_/g, ' ')
                        .split(' ')
                        .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
                        .join(' ');
                    };
                    
                    return (
                      <>
                        {featuresArray.slice(0, 4).map((feature, index) => (
                          <div key={index} className="flex items-center space-x-2">
                            <Check className={`w-3 h-3 sm:w-4 sm:h-4 ${isTrialExpired ? 'text-gray-400' : isTrialAlreadyActive ? 'text-[#9E005C]' : isPro ? 'text-[#FF4D94]' : 'text-[#9E005C]'}`} />
                            <span className={`text-xs sm:text-sm ${isTrialExpired ? 'text-gray-500' : isTrialAlreadyActive ? 'text-gray-700' : 'text-gray-700'}`}>{formatFeature(feature)}</span>
                          </div>
                        ))}
                        {featuresArray.length > 4 && (
                          <div className="text-xs text-gray-500 text-center">
                            +{featuresArray.length - 4} more features
                          </div>
                        )}
                        {featuresArray.length === 0 && (
                          <div className="text-sm text-gray-700">
                            Features included in this plan
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
                
                <button
                  onClick={() => {
                    // Allow clicking on expired paid plans to renew/upgrade
                    // Only disable for expired trials or already active plans
                    if (!isTrialExpired && !isTrialAlreadyActive && !isPaidPlanActive) {
                      handleSubscribe(plan.name);
                    }
                  }}
                  disabled={loadingPlan === plan.name || isTrialExpired || isTrialAlreadyActive || isPaidPlanActive}
                  className={`w-full py-2 sm:py-2.5 rounded-lg font-medium transition-all duration-300 flex items-center justify-center text-xs sm:text-sm ${
                    isTrialExpired
                      ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                      : isPaidPlanExpired
                      ? 'bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white hover:from-[#9E005C] hover:to-[#FF4D94] hover:scale-105'
                      : isTrialAlreadyActive || isPaidPlanActive
                      ? 'bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white cursor-not-allowed opacity-75'
                      : isPro
                      ? 'bg-gradient-to-r from-[#FF4D94] to-[#9E005C] text-white hover:from-[#9E005C] hover:to-[#FF4D94]'
                      : 'bg-gradient-to-r from-[#9E005C] to-[#FF4D94] text-white hover:from-[#FF4D94] hover:to-[#9E005C]'
                  } ${loadingPlan === plan.name ? 'opacity-50 cursor-not-allowed' : (isTrialExpired || isTrialAlreadyActive || isPaidPlanActive) ? '' : 'hover:scale-105'}`}
                >
                  {loadingPlan === plan.name ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                      Processing...
                    </>
                  ) : isTrialExpired ? (
                    <>
                      Trial Period Ended
                    </>
                  ) : isPaidPlanExpired ? (
                    <>
                      Renew Plan →
                    </>
                  ) : isTrialAlreadyActive ? (
                    <>
                      <Clock className="w-4 h-4 mr-2" />
                      {(() => {
                        // Use trial_expires_at first, fallback to trial_end
                        const expirationDate = trialInfo?.trial_expires_at || trialInfo?.trial_end;
                        
                        if (expirationDate) {
                          try {
                            const now = new Date();
                            let expiresAt = new Date(expirationDate);
                            
                            // Handle invalid date
                            if (isNaN(expiresAt.getTime())) {
                              expiresAt = new Date(expirationDate + 'Z');
                            }
                            
                            // If still invalid, try without timezone
                            if (isNaN(expiresAt.getTime())) {
                              console.error('Cannot parse expiration date:', expirationDate);
                              return <span>Trial Active</span>;
                            }
                            
                            const diff = expiresAt - now;
                            
                            if (diff > 0) {
                              const days = Math.floor(diff / (1000 * 60 * 60 * 24));
                              const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                              const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                              const seconds = Math.floor((diff % (1000 * 60)) / 1000);
                              
                              // Use countdown state if available (updates every second), otherwise use calculated value
                              const displayCountdown = countdown || { days, hours, minutes, seconds };
                              
                              return (
                                <span className="font-mono">
                                  {displayCountdown.days}D {String(displayCountdown.hours).padStart(2, '0')}H {String(displayCountdown.minutes).padStart(2, '0')}M {String(displayCountdown.seconds).padStart(2, '0')}S
                                </span>
                              );
                            } else {
                              return <span>Expired</span>;
                            }
                          } catch (e) {
                            console.error('Error calculating countdown in button:', e, trialInfo);
                            return <span>Trial Active</span>;
                          }
                        }
                        return <span>Trial Active</span>;
                      })()}
                    </>
                  ) : (
                    <>
                      Choose {displayName}
                      <ArrowRight className="w-4 h-4 ml-2" />
                    </>
                  )}
                </button>
              </div>
            );
          })
          ) : (
            <div className="col-span-full text-center py-8">
              <p className="text-gray-500">No subscription plans available. Please try again later.</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center mt-6 sm:mt-8">
          <p className="text-gray-500 text-xs sm:text-sm mb-2 px-4 sm:px-0">
            All plans include access to Emily's AI agents. Cancel anytime.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center space-y-1 sm:space-y-0 sm:space-x-4 text-xs text-gray-500">
            <span>✓ Secure payment</span>
            <span className="hidden sm:inline">•</span>
            <span>✓ 30-day money back</span>
            <span className="hidden sm:inline">•</span>
            <span>✓ Cancel anytime</span>
          </div>
        </div>
        </div>
      </div>
    </div>
  );
};

export default SubscriptionSelector;

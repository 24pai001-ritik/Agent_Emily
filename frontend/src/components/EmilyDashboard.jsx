import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useNotifications } from '../contexts/NotificationContext'
import { onboardingAPI } from '../services/onboarding'
import { supabase } from '../lib/supabase'
import SideNavbar from './SideNavbar'

const API_BASE_URL = (import.meta.env.VITE_API_URL || 'https://agent-emily.onrender.com').replace(/\/$/, '')
import MobileNavigation from './MobileNavigation'
import LoadingBar from './LoadingBar'
import MainContentLoader from './MainContentLoader'
import Chatbot from './Chatbot'
import RecentTasks from './RecentTasks'
import CustomContentChatbot from './CustomContentChatbot'
import ContentCard from './ContentCard'
import { Sparkles, TrendingUp, Users, Target, BarChart3, FileText, Calendar, PanelRight, PanelLeft, X, ChevronRight, Video, Phone, ChevronDown, MessageSquare, RefreshCw } from 'lucide-react'
import WhatsAppMessageModal from './WhatsAppMessageModal'

// Voice Orb Component with animated border (spring-like animation)
const VoiceOrb = ({ isSpeaking }) => {
  const [borderWidth, setBorderWidth] = useState(0)
  const velocityRef = useRef(0)
  const animationRef = useRef(null)
  const lastTimeRef = useRef(performance.now())

  useEffect(() => {
    if (isSpeaking) {
      // Spring animation parameters (similar to React Native Reanimated)
      const stiffness = 90
      const damping = 12
      const mass = 0.5
      const targetWidth = 8 + Math.random() * 4 // Vary between 8-12px based on "volume"
      
      const animate = (currentTime) => {
        const deltaTime = (currentTime - lastTimeRef.current) / 16.67 // Normalize to ~60fps
        lastTimeRef.current = currentTime
        
        setBorderWidth(prev => {
          const current = prev
          const diff = targetWidth - current
          
          // Spring physics: F = -kx - bv
          const springForce = (stiffness / mass) * diff
          const dampingForce = (damping / mass) * velocityRef.current
          const acceleration = springForce - dampingForce
          
          // Update velocity
          velocityRef.current += acceleration * (deltaTime * 0.01)
          velocityRef.current *= 0.95 // Additional damping
          
          // Update position
          const newWidth = current + velocityRef.current * (deltaTime * 0.01)
          
          return Math.max(0, newWidth)
        })
        
        if (isSpeaking) {
          animationRef.current = requestAnimationFrame(animate)
        }
      }
      lastTimeRef.current = performance.now()
      animationRef.current = requestAnimationFrame(animate)
    } else {
      // Smoothly return to 0 with spring animation
      const stiffness = 90
      const damping = 12
      const mass = 0.5
      const targetWidth = 0
      
      const animate = (currentTime) => {
        const deltaTime = (currentTime - lastTimeRef.current) / 16.67
        lastTimeRef.current = currentTime
        
        setBorderWidth(prev => {
          if (prev < 0.1 && Math.abs(velocityRef.current) < 0.1) {
            velocityRef.current = 0
            return 0
          }
          
          const current = prev
          const diff = targetWidth - current
          
          const springForce = (stiffness / mass) * diff
          const dampingForce = (damping / mass) * velocityRef.current
          const acceleration = springForce - dampingForce
          
          velocityRef.current += acceleration * (deltaTime * 0.01)
          velocityRef.current *= 0.95
          
          const newWidth = current + velocityRef.current * (deltaTime * 0.01)
          
          return Math.max(0, newWidth)
        })
        
        if (borderWidth > 0.1 || Math.abs(velocityRef.current) > 0.1) {
          animationRef.current = requestAnimationFrame(animate)
        }
      }
      lastTimeRef.current = performance.now()
      animationRef.current = requestAnimationFrame(animate)
    }

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [isSpeaking])

  return (
    <div className="relative flex items-center justify-center">
      {/* Outer animated border container */}
      <div 
        className="absolute rounded-full border-2 flex items-center justify-center"
        style={{
          width: '290px',
          height: '290px',
          borderRadius: '145px',
          borderWidth: `${borderWidth}px`,
          borderColor: isSpeaking ? 'rgb(96, 165, 250)' : 'transparent',
          transition: 'border-color 0.2s ease',
        }}
      >
        {/* Inner orb */}
        <div 
          className="rounded-full bg-gradient-to-br from-pink-400 to-purple-500 flex items-center justify-center"
          style={{
            width: '280px',
            height: '280px',
            borderRadius: '140px',
          }}
        >
          <span className="text-white font-bold text-4xl">E</span>
        </div>
      </div>
    </div>
  )
}

// Import components directly

function EmilyDashboard() {
  const { user, logout } = useAuth()
  const { showContentGeneration, showSuccess, showError, showInfo } = useNotifications()
  const navigate = useNavigate()
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isPanelOpen, setIsPanelOpen] = useState(true)
  const [conversations, setConversations] = useState([])
  const [loadingConversations, setLoadingConversations] = useState(false)
  const chatbotRef = useRef(null)
  const [selectedDate, setSelectedDate] = useState(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return today
  })
  const hasSetInitialDate = useRef(false)
  const [isCallActive, setIsCallActive] = useState(false)
  const [callStatus, setCallStatus] = useState('idle') // 'idle', 'requesting', 'connecting', 'connected'
  const [isCallSpeaking, setIsCallSpeaking] = useState(false)
  const [messageFilter, setMessageFilter] = useState('all') // 'all', 'emily', 'chase', 'leo'
  const [filterDropdownOpen, setFilterDropdownOpen] = useState(false)
  const [showCustomContentChatbot, setShowCustomContentChatbot] = useState(false)
  const [showWhatsAppModal, setShowWhatsAppModal] = useState(false)
  const [showMobileChatHistory, setShowMobileChatHistory] = useState(false)

  const handleCallClick = async () => {
    if (isCallActive) {
      // End call
      setIsCallActive(false)
      setCallStatus('idle')
      if (chatbotRef.current && chatbotRef.current.endCall) {
        chatbotRef.current.endCall()
      }
    } else {
      // Start call
      setCallStatus('requesting')
      try {
        // Request microphone permission
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        // Permission granted
        stream.getTracks().forEach(track => track.stop()) // Stop the stream, we just needed permission
        setCallStatus('connecting')
        setIsCallActive(true)
        
        // Say "connected" using OpenAI TTS
        try {
          const authToken = await getAuthToken()
          if (authToken) {
            const response = await fetch(`${API_BASE_URL}/chatbot/tts`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
              },
              body: JSON.stringify({ text: 'Connected' })
            })
            if (response.ok) {
              const audioBlob = await response.blob()
              const audioUrl = URL.createObjectURL(audioBlob)
              const audio = new Audio(audioUrl)
              audio.play()
              audio.onended = () => URL.revokeObjectURL(audioUrl)
            }
          }
        } catch (error) {
          console.error('Error playing connected sound:', error)
        }
        
        // Wait a bit then set to connected
        setTimeout(() => {
          setCallStatus('connected')
          if (chatbotRef.current && chatbotRef.current.startCall) {
            chatbotRef.current.startCall()
          }
        }, 1000)
      } catch (error) {
        console.error('Error accessing microphone:', error)
        setCallStatus('idle')
        showError('Microphone permission denied', 'Please allow microphone access to use voice calling.')
      }
    }
  }

  const handleRefreshChat = async () => {
    try {
      const authToken = await getAuthToken()
      if (!authToken) {
        showError('Authentication required', 'Please log in again.')
        return
      }

      // Clear the partial payload cache on the backend
      const response = await fetch(`${API_BASE_URL}/chatbot/chat/v2/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        }
      })

      if (response.ok) {
        // Clear the chat messages in the frontend
        if (chatbotRef.current && chatbotRef.current.clearChat) {
          chatbotRef.current.clearChat()
        }
        showSuccess('Chat refreshed', 'The conversation has been reset to start fresh.')
      } else {
        const errorData = await response.json().catch(() => ({ detail: 'Failed to refresh chat' }))
        showError('Failed to refresh chat', errorData.detail || 'Please try again.')
      }
    } catch (error) {
      console.error('Error refreshing chat:', error)
      showError('Error refreshing chat', error.message || 'Please try again.')
    }
  }

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const response = await onboardingAPI.getProfile()
        setProfile(response.data)
      } catch (error) {
        console.error('Error fetching profile:', error)
        // If profile doesn't exist, that's okay - user just completed onboarding
        setProfile(null)
      } finally {
        setLoading(false)
      }
    }

    if (user) {
      fetchProfile()
    } else {
      setLoading(false)
    }
  }, [user])

  // Fetch all conversations when panel opens
  useEffect(() => {
    if (isPanelOpen && user) {
      fetchAllConversations()
    }
  }, [isPanelOpen, user])

  // Set selectedDate to the most recent conversation date when conversations are first loaded
  useEffect(() => {
    if (conversations.length > 0 && !hasSetInitialDate.current) {
      const grouped = groupConversationsByDate(conversations)
      if (grouped.length > 0) {
        // Get the most recent date (first in sorted array)
        const mostRecentDate = grouped[0].dateObj
        setSelectedDate(new Date(mostRecentDate))
        hasSetInitialDate.current = true
      }
    }
  }, [conversations])

  const getAuthToken = async () => {
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token
  }

  const fetchAllConversations = async () => {
    setLoadingConversations(true)
    try {
      const authToken = await getAuthToken()
      if (!authToken) {
        console.error('No auth token available')
        setLoadingConversations(false)
        return
      }

      const response = await fetch(`${API_BASE_URL}/chatbot/conversations?all=true`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        }
      })

      if (response.ok) {
        const data = await response.json()
        if (data.success && data.conversations) {
          setConversations(data.conversations)
        }
      }
    } catch (error) {
      console.error('Error fetching conversations:', error)
    } finally {
      setLoadingConversations(false)
    }
  }

  // Group conversations by date and get only the last conversation per date
  const groupConversationsByDate = (conversations) => {
    const grouped = {}
    const dateMap = {} // Map dateKey to actual Date object for sorting
    
    conversations.forEach(conv => {
      const date = new Date(conv.created_at)
      const dateKey = date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
      })
      
      if (!grouped[dateKey]) {
        grouped[dateKey] = []
        // Store the date object for sorting (use start of day)
        const dateForSorting = new Date(date)
        dateForSorting.setHours(0, 0, 0, 0)
        dateMap[dateKey] = dateForSorting
      }
      grouped[dateKey].push(conv)
    })

    // Sort dates (newest first) using the date objects
    const sortedDates = Object.keys(grouped).sort((a, b) => {
      return dateMap[b] - dateMap[a]
    })

    // Return only the last conversation for each date
    return sortedDates.map(date => {
      const dateConversations = grouped[date].sort((a, b) => 
        new Date(a.created_at) - new Date(b.created_at)
      )
      // Get the last conversation (most recent)
      const lastConversation = dateConversations[dateConversations.length - 1]
      // Also store the date object for filtering
      const dateObj = dateMap[date]
      
      return {
        date,
        dateObj, // Store date object for filtering
        lastConversation,
        allConversations: dateConversations // Store all conversations for this date
      }
    })
  }

  // Function to load conversations for a specific date
  const loadConversationsForDate = async (dateObj) => {
    try {
      const authToken = await getAuthToken()
      if (!authToken) {
        console.error('No auth token available')
        return
      }

      // Update selected date in header (use the date object directly to avoid timezone issues)
      setSelectedDate(new Date(dateObj))

      // Calculate date range for the selected date
      const startDate = new Date(dateObj)
      startDate.setHours(0, 0, 0, 0)
      const endDate = new Date(dateObj)
      endDate.setHours(23, 59, 59, 999)

      // Filter from already loaded conversations
      const dateConversations = conversations.filter(conv => {
        const convDate = new Date(conv.created_at)
        return convDate >= startDate && convDate <= endDate
      })

      // Convert to message format and load in chatbot
      const conversationMessages = dateConversations
        .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
        .map(conv => {
          // Handle metadata - it might be None, dict, or string
          let metadata = conv.metadata
          if (typeof metadata === 'string') {
            try {
              metadata = JSON.parse(metadata)
            } catch {
              metadata = {}
            }
          }
          if (!metadata) metadata = {}
          
          return {
            id: `conv-${conv.id}`,
            type: conv.message_type === 'user' ? 'user' : 'bot',
            content: conv.content,
            timestamp: conv.created_at,
            isNew: false,
            scheduledMessageId: metadata?.scheduled_message_id || null
          }
        })

      // Remove duplicates based on scheduled_message_id
      const seenScheduledIds = new Set()
      const uniqueMessages = []
      for (const msg of conversationMessages) {
        if (msg.scheduledMessageId) {
          if (seenScheduledIds.has(msg.scheduledMessageId)) {
            continue
          }
          seenScheduledIds.add(msg.scheduledMessageId)
        }
        uniqueMessages.push(msg)
      }

      // Pass to chatbot via ref
      if (chatbotRef.current && chatbotRef.current.loadConversations) {
        chatbotRef.current.loadConversations(uniqueMessages)
      }
    } catch (error) {
      console.error('Error loading conversations for date:', error)
    }
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-red-600 mb-4">Not Authenticated</h1>
          <p className="text-gray-600">Please log in to access the dashboard.</p>
        </div>
      </div>
    )
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (filterDropdownOpen && !event.target.closest('.filter-dropdown-container')) {
        setFilterDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [filterDropdownOpen])

  return (
    <div className="min-h-screen bg-white">
      {/* Mobile Navigation */}
      <MobileNavigation 
        setShowCustomContentChatbot={() => {}} // Dashboard doesn't have these functions
        handleGenerateContent={() => {}}
        generating={false}
        fetchingFreshData={false}
        onOpenChatHistory={() => {
          setShowMobileChatHistory(true)
          if (!conversations.length && user) {
            fetchAllConversations()
          }
        }}
        showChatHistory={showMobileChatHistory}
      />
      
      {/* Side Navbar */}
      <SideNavbar />
      
      {/* Main Content */}
      <div className="md:ml-48 xl:ml-64 flex flex-col h-screen overflow-hidden">
        {/* Header */}
        <div className="hidden md:block bg-white shadow-sm border-b z-30 flex-shrink-0">
          <div className="px-4 lg:px-6 py-3 lg:py-4">
            <div className="flex justify-between items-center">
              <div className="hidden md:flex items-center gap-3">
                <Users className="w-5 h-5 text-gray-600" />
                <div className="relative filter-dropdown-container">
                  <button
                    onClick={() => setFilterDropdownOpen(!filterDropdownOpen)}
                    className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-gray-100 transition-colors text-sm lg:text-base text-gray-900"
                  >
                    <span>Discussions</span>
                    <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${filterDropdownOpen ? 'rotate-180' : ''}`} />
                  </button>
                  {filterDropdownOpen && (
                    <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 min-w-[160px]">
                      <button
                        onClick={() => {
                          setMessageFilter('all')
                          setFilterDropdownOpen(false)
                        }}
                        className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg ${
                          messageFilter === 'all' ? 'bg-gray-50 font-medium' : ''
                        }`}
                      >
                        All Messages
                      </button>
                      <button
                        onClick={() => {
                          setMessageFilter('emily')
                          setFilterDropdownOpen(false)
                        }}
                        className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg ${
                          messageFilter === 'emily' ? 'bg-gray-50 font-medium' : ''
                        }`}
                      >
                        Emily
                      </button>
                      <button
                        onClick={() => {
                          setMessageFilter('chase')
                          setFilterDropdownOpen(false)
                        }}
                        className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg ${
                          messageFilter === 'chase' ? 'bg-gray-50 font-medium' : ''
                        }`}
                      >
                        Chase
                      </button>
                      <button
                        onClick={() => {
                          setMessageFilter('leo')
                          setFilterDropdownOpen(false)
                        }}
                        className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg ${
                          messageFilter === 'leo' ? 'bg-gray-50 font-medium' : ''
                        }`}
                      >
                        Leo
                      </button>
                    </div>
                  )}
                </div>
                <span className="text-gray-400">|</span>
                <div className="text-sm lg:text-base text-gray-900">
                  {profile?.business_name || user?.user_metadata?.name || 'you'}
                </div>
                <span className="text-gray-400">|</span>
                <div className="text-sm lg:text-base text-gray-700">
                  {selectedDate.toLocaleDateString('en-US', { 
                    year: 'numeric', 
                    month: 'long', 
                    day: 'numeric' 
                  })}
                </div>
              </div>
              
              <div className="flex items-center gap-2">
                {/* WhatsApp Message Button */}
                <button
                  onClick={() => setShowWhatsAppModal(true)}
                  className="p-2 rounded-md hover:bg-green-50 transition-colors border border-green-200 bg-green-50"
                  title="Send WhatsApp Message"
                >
                  <MessageSquare className="w-5 h-5 text-green-600" />
                </button>
                
                {/* Video and Call Icons */}
                <button
                  className="p-2 rounded-md hover:bg-gray-100 transition-colors border border-gray-200"
                  title="Video"
                >
                  <Video className="w-5 h-5 text-gray-700" />
                </button>
                <button
                  onClick={handleCallClick}
                  className={`p-2 rounded-md transition-colors border ${
                    isCallActive 
                      ? 'bg-red-100 border-red-300 hover:bg-red-200' 
                      : 'hover:bg-gray-100 border-gray-200'
                  }`}
                  title={isCallActive ? "End Call" : "Call"}
                >
                  <Phone className={`w-5 h-5 ${isCallActive ? 'text-red-600' : 'text-gray-700'}`} />
                </button>
                
                {/* Panel Toggle Button */}
                <button
                  onClick={() => setIsPanelOpen(!isPanelOpen)}
                  className="p-2 rounded-md hover:bg-gray-100 transition-colors border border-gray-200"
                  title={isPanelOpen ? "Close Panel" : "Open Panel"}
                >
                  {isPanelOpen ? (
                    <PanelLeft className="w-5 h-5 text-gray-700" />
                  ) : (
                    <PanelRight className="w-5 h-5 text-gray-700" />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content Area */}
        <div className="flex-1 flex items-start bg-gray-50" style={{ minHeight: 0, overflow: 'hidden' }}>
            <div className="w-full h-full flex gap-2">
                {/* Main Chat Area */}
              <div className="flex-1 h-full">
                <div className="bg-white h-full relative">
                  <Chatbot 
                    profile={profile} 
                    ref={chatbotRef} 
                    isCallActive={isCallActive} 
                    callStatus={callStatus} 
                    onSpeakingChange={setIsCallSpeaking} 
                    messageFilter={messageFilter}
                    useV2={true}
                    onOpenCustomContent={() => setShowCustomContentChatbot(true)}
                    isModalOpen={showCustomContentChatbot}
                    onRefreshChat={handleRefreshChat}
                  />
                </div>
              </div>

              {/* Right Side Panel - Part of main content */}
              <div 
                className={`hidden md:flex bg-white border-l border-gray-200 transition-all duration-300 ease-in-out overflow-hidden h-full ${
                  isPanelOpen ? 'w-48 xl:w-64' : 'w-0'
                }`}
              >
                {isPanelOpen && (
                  <div className="h-full flex flex-col">
                    {/* Panel Header */}
                    <div className="p-4 border-b border-gray-200 flex items-center justify-between bg-gray-50 flex-shrink-0">
                      <h2 className="text-lg font-semibold text-gray-900">
                        {isCallActive ? 'Calling Emily' : 'Past Discussions'}
                      </h2>
                      <button
                        onClick={() => setIsPanelOpen(false)}
                        className="p-1.5 rounded-md hover:bg-gray-200 transition-colors"
                        title="Collapse Panel"
                      >
                        <ChevronRight className="w-5 h-5 text-gray-600" />
                      </button>
                    </div>

                    {/* Call Display in Right Panel */}
                    {isCallActive && (
                      <div className="border-b border-gray-200 bg-green-50">
                        <div className="p-4 flex items-center gap-3">
                          <div className="relative">
                            <Phone className="w-5 h-5 text-green-600" />
                            <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 rounded-full animate-pulse"></div>
                            <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 rounded-full animate-ping opacity-75"></div>
                          </div>
                          <span className="text-sm font-medium text-green-700">
                            In call with Emily
                          </span>
                        </div>
                        <div className="px-4 pb-4">
                          <button
                            onClick={handleCallClick}
                            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors text-sm font-medium"
                          >
                            <Phone className="w-4 h-4 rotate-135" />
                            <span>Disconnect</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Panel Content */}
                    <div className="flex-1 overflow-y-auto p-4">
                      {isCallActive ? (
                        /* Animated Sound Orb */
                        <div className="flex items-center justify-center h-full">
                          <VoiceOrb isSpeaking={isCallSpeaking} />
                        </div>
                      ) : loadingConversations ? (
                        <div className="flex items-center justify-center py-8">
                          <div className="text-sm text-gray-500">Loading conversations...</div>
                        </div>
                      ) : conversations.length === 0 ? (
                        <div className="flex items-center justify-center py-8">
                          <div className="text-sm text-gray-500">No conversations yet</div>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {groupConversationsByDate(conversations).map(({ date, dateObj, lastConversation }) => {
                            if (!lastConversation) return null
                            
                            const isUser = lastConversation.message_type === 'user'
                            const preview = lastConversation.content?.substring(0, 50) + (lastConversation.content?.length > 50 ? '...' : '')
                            const messageDate = new Date(lastConversation.created_at)
                            const formattedDate = messageDate.toLocaleDateString('en-US', { 
                              month: 'short', 
                              day: 'numeric',
                              year: messageDate.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
                            })
                            
                            // Check if this date is selected
                            const isSelected = selectedDate && 
                              selectedDate.toDateString() === new Date(dateObj).toDateString()
                            
                            return (
                              <div key={date}>
                                <div
                                  onClick={() => {
                                    setSelectedDate(new Date(dateObj))
                                    loadConversationsForDate(dateObj)
                                  }}
                                  className={`p-2 rounded-lg cursor-pointer transition-colors ${
                                    isSelected 
                                      ? 'bg-gray-100'
                                      : 'hover:bg-gray-50'
                                  }`}
                                >
                                  <div className="flex items-center gap-2">
                                    <div className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-sm ${
                                      isUser ? 'bg-pink-400' : 'bg-gradient-to-br from-pink-400 to-purple-500'
                                    }`}>
                                      {isUser ? (
                                        profile?.logo_url ? (
                                          <img src={profile.logo_url} alt="User" className="w-10 h-10 rounded-full object-cover" />
                                        ) : (
                                          <span className="text-white">U</span>
                                        )
                                      ) : (
                                        <span className="text-white font-bold">E</span>
                                      )}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center justify-between mb-1">
                                        <span className={`text-xs font-medium ${isUser ? 'text-pink-700' : 'text-purple-700'}`}>
                                          {isUser ? 'You' : 'Emily'}
                                        </span>
                                        <span className="text-xs text-gray-400">{formattedDate}</span>
                                      </div>
                                      <p className="text-xs text-gray-700 line-clamp-2">{preview}</p>
                  </div>
                </div>
              </div>
            </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}
          </div>
        </div>
      </div>
      </div>

      {/* Custom Content Chatbot Modal */}
      <CustomContentChatbot
        isOpen={showCustomContentChatbot}
        onClose={() => setShowCustomContentChatbot(false)}
        onContentCreated={async (content) => {
          console.log('onContentCreated called with content:', content)
          setShowCustomContentChatbot(false)
          
          // Create chatbot message with post card
          if (content && user?.id) {
            try {
              console.log('Creating chatbot message for post:', content)
              
              // Format scheduled date and time
              const scheduledDate = content.scheduled_date || content.scheduled_at?.split('T')[0]
              const scheduledTime = content.scheduled_time || content.scheduled_at?.split('T')[1]?.split('.')[0] || '12:00:00'
              
              let formattedDate = 'Not scheduled'
              let formattedTime = ''
              
              if (scheduledDate) {
                try {
                  const dateObj = new Date(`${scheduledDate}T${scheduledTime}`)
                  if (!isNaN(dateObj.getTime())) {
                    formattedDate = dateObj.toLocaleDateString('en-US', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric'
                    })
                    formattedTime = dateObj.toLocaleTimeString('en-US', {
                      hour: 'numeric',
                      minute: '2-digit',
                      hour12: true
                    })
                  }
                } catch (dateError) {
                  console.error('Error formatting date:', dateError)
                }
              }
              
              const businessName = profile?.business_name || user?.user_metadata?.name || 'your business'
              
              // Create message content
              const messageContent = `Generated this post for ${businessName}`
              
              // Create chatbot message with post data in metadata
              const chatbotMessageData = {
                user_id: user.id,
                message_type: 'bot',
                content: messageContent,
                intent: 'post_generated',
                metadata: {
                  sender: 'leo',
                  post_data: content,
                  scheduled_date: formattedDate,
                  scheduled_time: formattedTime,
                  notification_type: 'post_generated'
                }
              }
              
              console.log('Inserting chatbot message:', chatbotMessageData)
              
              // Insert into Supabase
              const { data, error } = await supabase
                .from('chatbot_conversations')
                .insert(chatbotMessageData)
                .select()
                .single()
              
              if (error) {
                console.error('Error creating chatbot message:', error)
                showError('Failed to create chatbot notification')
              } else {
                console.log('Chatbot message created successfully:', data)
                // The realtime subscription should pick this up automatically
              }
            } catch (error) {
              console.error('Error handling post creation:', error)
              showError('Failed to create chatbot notification')
            }
          } else {
            console.warn('onContentCreated called but content or user is missing:', { content, userId: user?.id })
          }
        }}
      />
      
      {/* WhatsApp Message Modal */}
      <WhatsAppMessageModal 
        isOpen={showWhatsAppModal}
        onClose={() => setShowWhatsAppModal(false)}
      />

      {/* Mobile Chat History Panel - Full Screen */}
      {showMobileChatHistory && (
        <div className="md:hidden fixed inset-0 z-50 bg-white">
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-4 border-b border-gray-200 flex items-center justify-between bg-gray-50 flex-shrink-0">
              <h2 className="text-lg font-semibold text-gray-900">Chat History</h2>
              <button
                onClick={() => setShowMobileChatHistory(false)}
                className="p-2 rounded-md hover:bg-gray-200 transition-colors"
                title="Close"
              >
                <X className="w-5 h-5 text-gray-600" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {loadingConversations ? (
                <div className="flex items-center justify-center py-8">
                  <div className="text-sm text-gray-500">Loading conversations...</div>
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex items-center justify-center py-8">
                  <div className="text-sm text-gray-500">No conversations yet</div>
                </div>
              ) : (
                <div className="space-y-4">
                  {groupConversationsByDate(conversations).map(({ date, dateObj, lastConversation }) => {
                    if (!lastConversation) return null
                    
                    const isUser = lastConversation.message_type === 'user'
                    const preview = lastConversation.content?.substring(0, 50) + (lastConversation.content?.length > 50 ? '...' : '')
                    const messageDate = new Date(lastConversation.created_at)
                    const formattedDate = messageDate.toLocaleDateString('en-US', { 
                      month: 'short', 
                      day: 'numeric',
                      year: messageDate.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
                    })
                    
                    // Check if this date is selected
                    const isSelected = selectedDate && 
                      selectedDate.toDateString() === new Date(dateObj).toDateString()
                    
                    return (
                      <div key={date}>
                        <div
                          onClick={() => {
                            setSelectedDate(new Date(dateObj))
                            loadConversationsForDate(dateObj)
                            setShowMobileChatHistory(false)
                          }}
                          className={`p-3 rounded-lg cursor-pointer transition-colors ${
                            isSelected 
                              ? 'bg-gray-100'
                              : 'hover:bg-gray-50'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-sm ${
                              isUser ? 'bg-pink-400' : 'bg-gradient-to-br from-pink-400 to-purple-500'
                            }`}>
                              {isUser ? (
                                profile?.logo_url ? (
                                  <img src={profile.logo_url} alt="User" className="w-10 h-10 rounded-full object-cover" />
                                ) : (
                                  <span className="text-white">U</span>
                                )
                              ) : (
                                <span className="text-white font-bold">E</span>
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between mb-1">
                                <span className={`text-sm font-medium ${isUser ? 'text-pink-700' : 'text-purple-700'}`}>
                                  {isUser ? 'You' : 'Emily'}
                                </span>
                                <span className="text-xs text-gray-400">{formattedDate}</span>
                              </div>
                              <p className="text-sm text-gray-700 line-clamp-2">{preview}</p>
                              <p className="text-xs text-gray-500 mt-1">{date}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default EmilyDashboard


import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useNotifications } from '../contexts/NotificationContext'
import { supabase } from '../lib/supabase'
import { Send, User, Mic, Sparkles, Bot, Copy, Reply, Trash2, Heart, MessageCircle, Share2, Bookmark, MoreHorizontal, RefreshCw, Instagram, Facebook, Linkedin, Youtube, Twitter } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Get API URL with proper fallback
const getApiBaseUrl = () => {
  const envUrl = import.meta.env.VITE_API_URL
  if (envUrl) {
    if (envUrl.startsWith(':')) {
      return `http://localhost${envUrl}`
    }
    if (!envUrl.startsWith('http://') && !envUrl.startsWith('https://')) {
      return `http://${envUrl}`
    }
    return envUrl
  }
  return 'http://localhost:8000'
}
const API_BASE_URL = getApiBaseUrl().replace(/\/$/, '')

const Chatbot = React.forwardRef(({ profile, isCallActive = false, callStatus = 'idle', onSpeakingChange, messageFilter = 'all', useV2 = false, onRefreshChat = null }, ref) => {
  const { user } = useAuth()
  const { showError, showSuccess } = useNotifications()
  const navigate = useNavigate()
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [expandedMessages, setExpandedMessages] = useState(new Set())
  const [expandedEmailBoxes, setExpandedEmailBoxes] = useState(new Set())
  const [hoveredMessageId, setHoveredMessageId] = useState(null)
  const [replyingToMessage, setReplyingToMessage] = useState(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const isLoadingConversationsRef = useRef(false)
  const recognitionRef = useRef(null)
  const synthesisRef = useRef(null)
  const isListeningRef = useRef(false)
  const currentAudioRef = useRef(null)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const inputRecognitionRef = useRef(null)
  const isSelectingTextRef = useRef(false)
  const mouseDownTimeRef = useRef(0)
  const fileInputRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "auto" })
  }

  // Helper function to check if any modal is open
  const isModalOpen = () => {
    // Check for common modal indicators
    const modals = document.querySelectorAll('[role="dialog"], .modal, [class*="modal"], [class*="Modal"]')
    for (let modal of modals) {
      const style = window.getComputedStyle(modal)
      if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
        return true
      }
    }
    // Check for backdrop/overlay elements
    const backdrops = document.querySelectorAll('[class*="backdrop"], [class*="overlay"], [class*="z-50"]')
    for (let backdrop of backdrops) {
      const style = window.getComputedStyle(backdrop)
      if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
        // Check if it's actually visible (not just in DOM)
        const rect = backdrop.getBoundingClientRect()
        if (rect.width > 0 && rect.height > 0) {
          return true
        }
      }
    }
    return false
  }

  useEffect(() => {
    scrollToBottom()
    // Aggressively refocus after messages update - NO RESTRICTIONS
    if (inputRef.current && !isCallActive && !isLoading && !isStreaming) {
      // Use requestAnimationFrame for immediate refocus after messages update
      requestAnimationFrame(() => {
        if (!isCallActive && !isLoading && !isStreaming && inputRef.current) {
          inputRef.current.focus()
        }
      })
    }
  }, [messages, isLoading, isStreaming, isCallActive])

  // Auto-focus input when component mounts and maintain focus
  useEffect(() => {
    // Use a small delay to ensure the component is fully rendered
    const timer = setTimeout(() => {
    if (inputRef.current && !isCallActive && !isModalOpen()) {
      inputRef.current.focus()
    }
    }, 100)
    
    return () => clearTimeout(timer)
  }, [])

  // EXTRA AGGRESSIVE: Focus check on every render - NO RESTRICTIONS
  useEffect(() => {
    if (isCallActive || isLoading || isStreaming) return
    
    // Use requestAnimationFrame to check focus after render
    requestAnimationFrame(() => {
      if (inputRef.current && document.activeElement !== inputRef.current) {
        inputRef.current.focus()
      }
    })
  })

  // Keep focus on input field at all times - NO RESTRICTIONS
  useEffect(() => {
    if (isCallActive) return // Don't focus during calls
    
    const maintainFocus = () => {
      if (!inputRef.current) return
      
      // ALWAYS focus - no restrictions, no conditions
      if (document.activeElement !== inputRef.current) {
        inputRef.current.focus()
      }
    }

    // Set up interval to check and maintain focus (EXTREMELY aggressive)
    const focusInterval = setInterval(maintainFocus, 25) // Check every 25ms

    // Focus on any click - NO RESTRICTIONS
    const handleClick = (e) => {
      const target = e.target
      
      // If clicking anywhere except our input, refocus immediately
      if (target !== inputRef.current && !inputRef.current?.contains(target)) {
          setTimeout(() => {
          if (inputRef.current) {
            inputRef.current.focus()
          }
        }, 10)
      }
    }

    // Capture keyboard events to focus input when user types ANY KEYSTROKE - NO RESTRICTIONS
    const handleKeyDown = (e) => {
      // Focus on ANY keystroke (except Tab and Escape)
      if (e.key !== 'Tab' && e.key !== 'Escape' && inputRef.current) {
        // If input is not focused, focus it immediately
        if (document.activeElement !== inputRef.current) {
          // Focus synchronously
          inputRef.current.focus()
          
          // For printable characters, manually insert them since focus happened after keydown
          if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            // Prevent default to stop the key from being lost
            e.preventDefault()
            e.stopPropagation()
            
            // Get current value and cursor position
            const currentValue = inputMessage
            const cursorPos = inputRef.current.selectionStart || currentValue.length
            
            // Insert the character
            const newValue = currentValue.slice(0, cursorPos) + e.key + currentValue.slice(cursorPos)
            setInputMessage(newValue)
            
            // Set cursor position after the inserted character
            requestAnimationFrame(() => {
              if (inputRef.current) {
                inputRef.current.setSelectionRange(cursorPos + 1, cursorPos + 1)
              }
            })
          }
        }
      }
    }

    document.addEventListener('click', handleClick)
    // Use capture phase to intercept keydown events early, before they reach other handlers
    document.addEventListener('keydown', handleKeyDown, true)

    return () => {
      clearInterval(focusInterval)
      document.removeEventListener('click', handleClick)
      document.removeEventListener('keydown', handleKeyDown, true)
    }
  }, [isCallActive])

  // Text-to-speech for bot responses using OpenAI TTS
  const speakText = async (text) => {
    if (isCallActive && callStatus === 'connected') {
      try {
        // Cancel any ongoing speech
        if (currentAudioRef.current) {
          currentAudioRef.current.pause()
          currentAudioRef.current = null
        }
        
        const authToken = await getAuthToken()
        if (!authToken) {
          console.error('No auth token available for TTS')
          return
        }
        
        // Call backend TTS endpoint
        const response = await fetch(`${API_BASE_URL}/chatbot/tts`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`
          },
          body: JSON.stringify({ text })
        })
        
        if (!response.ok) {
          throw new Error(`TTS request failed: ${response.status}`)
        }
        
        // Get audio blob
        const audioBlob = await response.blob()
        const audioUrl = URL.createObjectURL(audioBlob)
        const audio = new Audio(audioUrl)
        audio.controls = false // Hide audio controls
        audio.style.display = 'none' // Hide audio element
        currentAudioRef.current = audio
        
        audio.onplay = () => {
          setIsSpeaking(true)
          if (onSpeakingChange) onSpeakingChange(true)
        }
        
        audio.onended = () => {
          setIsSpeaking(false)
          if (onSpeakingChange) onSpeakingChange(false)
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          // Resume listening after speech ends
          if (isCallActive && isListeningRef.current && recognitionRef.current) {
            try {
              recognitionRef.current.start()
            } catch (e) {
              console.log('Recognition already started')
            }
          }
        }
        
        audio.onerror = () => {
          setIsSpeaking(false)
          if (onSpeakingChange) onSpeakingChange(false)
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
        }
        
        await audio.play()
      } catch (error) {
        console.error('Error with TTS:', error)
        setIsSpeaking(false)
        if (onSpeakingChange) onSpeakingChange(false)
      }
    }
  }

  // Initialize speech recognition when call is active
  useEffect(() => {
    if (isCallActive && callStatus === 'connected') {
      // Initialize Speech Recognition
      if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
        const recognition = new SpeechRecognition()
        recognition.continuous = true
        recognition.interimResults = false
        recognition.lang = 'en-US'
        
        recognition.onresult = (event) => {
          const transcript = event.results[event.results.length - 1][0].transcript
          if (transcript.trim()) {
            setInputMessage(transcript)
            // Auto-send after a short delay
            setTimeout(() => {
              sendMessage(transcript)
            }, 500)
          }
        }
        
        recognition.onerror = (event) => {
          console.error('Speech recognition error:', event.error)
          if (event.error === 'no-speech') {
            // Restart listening if no speech detected
            if (isListeningRef.current && isCallActive) {
              setTimeout(() => {
                try {
                  recognition.start()
                } catch (e) {
                  console.log('Recognition already started')
                }
              }, 1000)
            }
          }
        }
        
        recognition.onend = () => {
          // Restart listening if call is still active
          if (isCallActive && isListeningRef.current) {
            setTimeout(() => {
              try {
                recognition.start()
              } catch (e) {
                console.log('Recognition already started')
              }
            }, 500)
          }
        }
        
        recognitionRef.current = recognition
        isListeningRef.current = true
        recognition.start()
      }
    } else {
      // Stop recognition when call ends
      if (recognitionRef.current) {
        isListeningRef.current = false
        try {
          recognitionRef.current.stop()
        } catch (e) {
          console.log('Recognition already stopped')
        }
        recognitionRef.current = null
      }
    }
    
    return () => {
      if (recognitionRef.current) {
        isListeningRef.current = false
        try {
          recognitionRef.current.stop()
        } catch (e) {
          console.log('Recognition already stopped')
        }
        recognitionRef.current = null
      }
    }
  }, [isCallActive, callStatus])

  // Cache key for localStorage
  const getCacheKey = () => {
    if (!user?.id) return null
    const today = new Date().toISOString().split('T')[0] // YYYY-MM-DD
    return `chatbot_messages_${user.id}_${today}`
  }

  // Load messages from cache
  const loadMessagesFromCache = () => {
    const cacheKey = getCacheKey()
    if (!cacheKey) return null
    
    try {
      const cached = localStorage.getItem(cacheKey)
      if (cached) {
        const parsed = JSON.parse(cached)
        // Check if cache is from today
        const cacheDate = parsed.date
        const today = new Date().toISOString().split('T')[0]
        if (cacheDate === today && parsed.messages && Array.isArray(parsed.messages)) {
          return parsed.messages
        }
      }
    } catch (error) {
      console.error('Error loading messages from cache:', error)
    }
    return null
  }

  // Save messages to cache (only called when new message is added)
  const saveMessagesToCache = (messagesToSave) => {
    const cacheKey = getCacheKey()
    if (!cacheKey) return
    
    try {
      const today = new Date().toISOString().split('T')[0]
      const cacheData = {
        date: today,
        messages: messagesToSave,
        lastUpdated: new Date().toISOString()
      }
      localStorage.setItem(cacheKey, JSON.stringify(cacheData))
    } catch (error) {
      console.error('Error saving messages to cache:', error)
      // Handle quota exceeded error
      if (error.name === 'QuotaExceededError') {
        console.warn('LocalStorage quota exceeded, clearing old cache entries')
        // Clear old cache entries (keep only last 7 days)
        try {
          const keys = Object.keys(localStorage)
          const cacheKeys = keys.filter(key => key.startsWith('chatbot_messages_'))
          if (cacheKeys.length > 7) {
            // Sort by key (which includes date) and remove oldest
            cacheKeys.sort().slice(0, cacheKeys.length - 7).forEach(key => {
              localStorage.removeItem(key)
            })
          }
        } catch (clearError) {
          console.error('Error clearing old cache:', clearError)
        }
      }
    }
  }

  // Load today's conversations when component mounts or when profile/user changes
  useEffect(() => {
    if (profile && user && !isLoadingConversationsRef.current) {
      // Load from cache synchronously (fast, non-blocking)
      const cachedMessages = loadMessagesFromCache()
      if (cachedMessages && cachedMessages.length > 0) {
        console.log('Loading messages from cache:', cachedMessages.length, 'messages')
        // Use setTimeout to ensure this doesn't block rendering
        setTimeout(() => {
          setMessages(cachedMessages)
        }, 0)
        // Fetch from API in background asynchronously
        Promise.resolve().then(() => loadTodayConversations())
      } else {
        // No cache, load from API asynchronously
        Promise.resolve().then(() => loadTodayConversations())
      }
    }
  }, [profile?.id, user?.id]) // Reload when profile or user changes

  // Subscribe to new chatbot messages via Supabase realtime
  useEffect(() => {
    if (!user?.id) return

    const channel = supabase
      .channel('chatbot_conversations')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'chatbot_conversations',
          filter: `user_id=eq.${user.id}`
        },
        (payload) => {
          const newMessage = payload.new
          
          // Parse metadata - handle string, object, or null
          let metadata = newMessage.metadata
          if (typeof metadata === 'string') {
            try {
              metadata = JSON.parse(metadata)
            } catch (e) {
              console.error('Failed to parse metadata JSON:', e)
              metadata = {}
            }
          }
          if (!metadata || typeof metadata !== 'object') {
            metadata = {}
          }
          
          // Extract content_data and options from metadata
          let contentData = metadata.content_data || null
          let options = metadata.options || null
          
          // If content_data is a string, parse it
          if (contentData && typeof contentData === 'string') {
            try {
              contentData = JSON.parse(contentData)
            } catch (e) {
              console.error('Failed to parse content_data JSON:', e)
              contentData = null
            }
          }
          
          // If options is a string, parse it
          if (options && typeof options === 'string') {
            try {
              options = JSON.parse(options)
            } catch (e) {
              console.error('Failed to parse options JSON:', e)
              options = null
            }
          }
          
          const isChase = metadata.sender === 'chase'
          
          // Only add if it's a new message (not already in messages)
          setMessages(prev => {
            // Check if message already exists
            const exists = prev.some(msg => 
              msg.conversationId === newMessage.id || 
              (msg.id && msg.id === `conv-${newMessage.id}`)
            )
            
            if (exists) return prev
            
            // Add new message
            const messageObj = {
              id: `conv-${newMessage.id}`,
              conversationId: newMessage.id,
              type: newMessage.message_type === 'user' ? 'user' : 'bot',
              content: newMessage.content,
              timestamp: newMessage.created_at,
              isNew: true,
              scheduledMessageId: metadata.scheduled_message_id || null,
              isChase: isChase,
              content_data: contentData, // Extract content_data from metadata
              options: options, // Extract options from metadata
              chaseMetadata: isChase ? {
                leadId: metadata.lead_id,
                leadName: metadata.lead_name,
                emailContent: metadata.email_content,
                emailSubject: metadata.email_subject
              } : null
            }
              
              const updatedMessages = [...prev, messageObj]
              
              // Update cache when new message is added
              saveMessagesToCache(updatedMessages)
            
            // Remove isNew flag after animation
            setTimeout(() => {
              setMessages(current => current.map(msg => 
                msg.id === messageObj.id && msg.isNew
                  ? { ...msg, isNew: false }
                  : msg
              ))
            }, 400)
            
              return updatedMessages
          })
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [user?.id])

  // Cleanup input recognition on unmount
  useEffect(() => {
    return () => {
      if (inputRecognitionRef.current) {
        try {
          inputRecognitionRef.current.stop()
        } catch (e) {
          // Ignore errors on cleanup
        }
        inputRecognitionRef.current = null
      }
    }
  }, [])

  const loadTodayConversations = async () => {
    // Prevent concurrent loads
    if (isLoadingConversationsRef.current) {
      return
    }
    
    isLoadingConversationsRef.current = true
    
    try {
      const authToken = await getAuthToken()
      
      if (!authToken) {
        console.error('No auth token available')
        isLoadingConversationsRef.current = false
        return
      }
      
      // Fetch today's conversations asynchronously (non-blocking)
      const response = await fetch(`${API_BASE_URL}/chatbot/conversations`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        }
      })

      if (!response.ok) {
        const errorText = await response.text()
        console.error('Failed to fetch conversations:', response.status, errorText)
        isLoadingConversationsRef.current = false
        // Still try to fetch scheduled messages
        fetchScheduledMessages()
        return
      }

      const data = await response.json()
      console.log('Conversations response:', data)
      
      if (data.success && data.conversations) {
        if (data.conversations.length > 0) {
          // Convert conversations to message format
          const conversationMessages = data.conversations.map(conv => {
            // Parse metadata - handle string, object, or null
            let metadata = conv.metadata
            if (typeof metadata === 'string') {
              try {
                metadata = JSON.parse(metadata)
              } catch (e) {
                console.error('Failed to parse metadata JSON:', e)
                metadata = {}
              }
            }
            if (!metadata || typeof metadata !== 'object') {
              metadata = {}
            }
            
            // Extract content_data and options from metadata
            let contentData = metadata.content_data || null
            let options = metadata.options || null
            
            // If content_data is a string, parse it
            if (contentData && typeof contentData === 'string') {
              try {
                contentData = JSON.parse(contentData)
              } catch (e) {
                console.error('Failed to parse content_data JSON:', e)
                contentData = null
              }
            }
            
            // If options is a string, parse it
            if (options && typeof options === 'string') {
              try {
                options = JSON.parse(options)
              } catch (e) {
                console.error('Failed to parse options JSON:', e)
                options = null
              }
            }
            
            const isChase = metadata.sender === 'chase'
            const isLeo = metadata.sender === 'leo'
            const isEmily = conv.message_type === 'bot' && !isChase && !isLeo
            
            return {
              id: `conv-${conv.id}`,
              conversationId: conv.id, // Store Supabase ID for deletion
              type: conv.message_type === 'user' ? 'user' : 'bot',
              content: conv.content,
              timestamp: conv.created_at,
              isNew: false,
              scheduledMessageId: metadata.scheduled_message_id || null,
              isChase: isChase,
              isLeo: isLeo,
              isEmily: isEmily,
              content_data: contentData, // Extract content_data from metadata
              options: options, // Extract options from metadata
              chaseMetadata: isChase ? {
                leadId: metadata.lead_id,
                leadName: metadata.lead_name,
                emailContent: metadata.email_content,
                emailSubject: metadata.email_subject
              } : null
            }
          })
          
          // Remove duplicates based on scheduled_message_id
          const seenScheduledIds = new Set()
          const uniqueMessages = []
          for (const msg of conversationMessages) {
            if (msg.scheduledMessageId) {
              if (seenScheduledIds.has(msg.scheduledMessageId)) {
                continue // Skip duplicate
              }
              seenScheduledIds.add(msg.scheduledMessageId)
            }
            uniqueMessages.push(msg)
          }
          
          // Sort by timestamp (oldest first)
          uniqueMessages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
          
          console.log('Setting messages:', uniqueMessages.length, 'messages')
            // Use setTimeout to batch state updates and avoid blocking
            setTimeout(() => {
          setMessages(uniqueMessages)
              // Update cache with fetched messages
              saveMessagesToCache(uniqueMessages)
            }, 0)
        } else {
          console.log('No conversations found for today - will generate scheduled messages up to current time')
          // If no conversations, start with empty array
            setTimeout(() => setMessages([]), 0)
            // Trigger generation of scheduled messages up to current time (async)
            Promise.resolve().then(async () => {
          try {
            const generateResponse = await fetch(`${API_BASE_URL}/chatbot/scheduled-messages/generate-today`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
              }
            })
            
            if (generateResponse.ok) {
              const generateData = await generateResponse.json()
              console.log('Generated messages:', generateData)
              // After generating, fetch scheduled messages to display them
              setTimeout(() => fetchScheduledMessages(), 500)
              isLoadingConversationsRef.current = false
              return // Exit early, fetchScheduledMessages will be called
            }
          } catch (error) {
            console.error('Error generating messages:', error)
          }
            })
        }
      } else {
        console.error('Invalid response format:', data)
          setTimeout(() => setMessages([]), 0)
      }
      
        // Then fetch and display scheduled messages (async, non-blocking)
        Promise.resolve().then(() => fetchScheduledMessages())
        
        // Reset loading flag after a short delay to allow state updates
        setTimeout(() => {
          isLoadingConversationsRef.current = false
        }, 100)
      
    } catch (error) {
      console.error('Error loading conversations:', error)
      // Still try to fetch scheduled messages (async)
      Promise.resolve().then(() => fetchScheduledMessages())
      isLoadingConversationsRef.current = false
    }
  }

  const sendMessage = async (messageText = null) => {
    const messageToSend = messageText || inputMessage
    if (!messageToSend.trim() || isLoading) return

    // Build message content with reply context if replying
    let finalMessage = messageToSend
    if (replyingToMessage) {
      finalMessage = `[Replying to: "${replyingToMessage.content.substring(0, 100)}${replyingToMessage.content.length > 100 ? '...' : ''}"]\n\n${messageToSend}`
    }

    const userMessage = {
      id: Date.now(),
      type: 'user',
      content: messageToSend,
      timestamp: new Date().toISOString(),
      replyingTo: replyingToMessage
    }

    setMessages(prev => {
      const updated = [...prev, userMessage]
      // Update cache when new message is added
      saveMessagesToCache(updated)
      return updated
    })
    setInputMessage('')
    setReplyingToMessage(null) // Clear reply context after sending
    setIsLoading(true)
    setIsStreaming(true)

    // Create a placeholder bot message for streaming with dots
    const botMessageId = Date.now() + 1
    const botMessage = {
      id: botMessageId,
      type: 'bot',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true
    }

    setMessages(prev => {
      const updated = [...prev, botMessage]
      // Update cache when new message is added
      saveMessagesToCache(updated)
      return updated
    })

    try {
      const authToken = await getAuthToken()
      
      // Use non-streaming endpoint when in call to avoid TTS issues
      // Use v2 endpoint if useV2 prop is true
      const endpoint = isCallActive && callStatus === 'connected' 
        ? `${API_BASE_URL}/chatbot/chat${useV2 ? '/v2' : ''}` 
        : `${API_BASE_URL}/chatbot/chat${useV2 ? '/v2' : ''}/stream`
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({
          message: finalMessage,
          user_id: user?.id,
          conversation_history: messages
            .filter(msg => (msg.type === 'user' || msg.type === 'bot') && msg.content && msg.content.trim()) // Include all user and bot messages with content (including greeting)
            .map(msg => ({
              type: msg.type,
              content: msg.content,
              role: msg.type === 'user' ? 'user' : 'assistant'
            }))
            .slice(0, -1) // Exclude the current placeholder bot message
        })
      })

      if (!response.ok) {
        // Try to get error message from response
        let errorMessage = `HTTP error! status: ${response.status}`
        try {
          const errorData = await response.json()
          errorMessage = errorData.detail || errorData.error || errorData.message || errorMessage
        } catch (e) {
          // If response isn't JSON, use status text
          errorMessage = response.statusText || errorMessage
        }
        throw new Error(errorMessage)
      }

      // Declare options at function scope so it's accessible in catch block
      let options = null

      // Handle non-streaming response (when in call)
      if (isCallActive && callStatus === 'connected') {
        const data = await response.json()
        const botResponse = data.response || data.content || ''
        const cleanContent = botResponse.replace(/🔍.*?\n|📅.*?\n|🔍.*?\n|✅.*?\n|📝.*?\n|❌.*?\n|📊.*?\n|📈.*?\n|🤖.*?\n|✨.*?\n|---CLEAR_PROGRESS---.*?\n/g, '').trim()
        options = data.options || null
        const contentData = data.content_data || null
        
        // Update bot message with full response, options, and content_data
        setMessages(prev => 
          prev.map(msg => 
            msg.id === botMessageId 
              ? { ...msg, content: cleanContent, isStreaming: false, options: options, content_data: contentData }
              : msg
          )
        )
        
        // Speak the response once
        if (cleanContent) {
          speakText(cleanContent)
        }
      } else {
        // Handle streaming response (normal mode)
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('No response body reader available')
      }

      let buffer = ''
      let isDone = false
        let finalContentData = null

      while (!isDone) {
        const { done, value } = await reader.read()
        
        if (done) {
          isDone = true
            // Check final buffer for CONTENT_DATA before breaking
            if (buffer && buffer.includes('CONTENT_DATA:')) {
              try {
                const contentDataMatch = buffer.match(/CONTENT_DATA:(.+)/)
                if (contentDataMatch) {
                  finalContentData = JSON.parse(contentDataMatch[1].trim())
                }
              } catch (e) {
                console.error('Error parsing final CONTENT_DATA:', e)
              }
            }
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
                const rawData = line.slice(6)
                console.log('📥 Raw SSE data received:', rawData.substring(0, 200))
                const data = JSON.parse(rawData)
                console.log('📦 Parsed SSE data:', data)
              
                // Check if this message contains options
                if (data.options) {
                  options = data.options
                  setMessages(prev => 
                    prev.map(msg => {
                      if (msg.id === botMessageId) {
                        return { ...msg, options: options, isStreaming: false }
                      }
                      return msg
                    })
                  )
                }
                
                // Check if this message contains content_data (from SSE stream)
                if (data.content_data) {
                  console.log('📷 Received content_data from SSE stream:', data.content_data)
                  console.log('   Images:', data.content_data.images)
                  console.log('   Images type:', typeof data.content_data.images)
                  console.log('   Is array?', Array.isArray(data.content_data.images))
                  finalContentData = data.content_data
                  setMessages(prev => 
                    prev.map(msg => {
                      if (msg.id === botMessageId) {
                        console.log('✅ Updating message with content_data:', data.content_data)
                        return { ...msg, content_data: data.content_data, isStreaming: false }
                      }
                      return msg
                    })
                  )
                }
              
              if (data.done) {
                isDone = true
                setIsStreaming(false)
                  // If done message has content_data, use it
                  if (data.content_data) {
                    finalContentData = data.content_data
                    console.log('📷 Final done message has content_data:', data.content_data)
                  }
                break
              }
              
              if (data.content) {
                  // Skip if content is the OPTIONS marker (already handled above)
                  if (data.content.includes('OPTIONS:')) {
                    continue
                  }
                  
                // Check if content contains CONTENT_DATA marker
                if (data.content.includes('CONTENT_DATA:')) {
                  try {
                    // Extract CONTENT_DATA from the content string
                    const contentDataMatch = data.content.match(/CONTENT_DATA:(.+)/s)
                    if (contentDataMatch) {
                      const contentDataJson = contentDataMatch[1].trim()
                      const contentData = JSON.parse(contentDataJson)
                      console.log('Parsed content_data from CONTENT_DATA marker:', contentData)
                      setMessages(prev => 
                        prev.map(msg => {
                          if (msg.id === botMessageId) {
                            return { ...msg, content_data: contentData, isStreaming: false }
                          }
                          return msg
                        })
                      )
                      // Remove CONTENT_DATA marker from content
                      const contentWithoutMarker = data.content.replace(/CONTENT_DATA:.*/s, '').trim()
                      if (contentWithoutMarker) {
                        setMessages(prev => 
                          prev.map(msg => {
                            if (msg.id === botMessageId) {
                              const currentContent = msg.content || ''
                              return { ...msg, content: currentContent + contentWithoutMarker, isStreaming: false }
                            }
                            return msg
                          })
                        )
                      }
                      continue
                    }
                  } catch (e) {
                    console.error('Error parsing CONTENT_DATA:', e)
                  }
                }
                  
                  // Skip error messages that are being streamed - we'll handle them in the catch block
                  if (data.content.startsWith('Error:') || data.content.includes('Sorry, I encountered an error')) {
                    console.error('Error content in stream:', data.content)
                    continue
                  }
                  
                // Check if this is a clear progress command
                if (data.content.includes('---CLEAR_PROGRESS---')) {
                  // Clear the progress messages by removing lines that look like progress
                  setMessages(prev => 
                      prev.map(msg => {
                        if (msg.id === botMessageId) {
                          const finalContent = msg.content.replace(/🔍.*?\n|📅.*?\n|🔍.*?\n|✅.*?\n|📝.*?\n|❌.*?\n|📊.*?\n|📈.*?\n|🤖.*?\n|✨.*?\n|---CLEAR_PROGRESS---.*?\n/g, '').trim()
                          return { 
                            ...msg, 
                            content: finalContent,
                              isStreaming: false,
                              options: options
                          }
                        }
                        return msg
                      })
                  )
                } else {
                  setMessages(prev => 
                      prev.map(msg => {
                        if (msg.id === botMessageId) {
                            const currentContent = msg.content || ''
                            const updatedContent = currentContent + data.content
                            return { ...msg, content: updatedContent, isStreaming: false, options: options }
                        }
                        return msg
                      })
                  )
                }
              }
                
                // Handle error flag in data - but don't append to existing content
                if (data.error) {
                  console.error('Error flag in stream data:', data)
                  // Don't modify message content if error occurs - just log it
                  // The catch block will handle actual errors
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e)
              }
            }
          }
        }
        
        // Final update with options and content_data if they exist (for streaming)
        if (options || finalContentData) {
          console.log('📦 Final update - options:', options, 'content_data:', finalContentData)
          setMessages(prev => 
            prev.map(msg => {
              if (msg.id === botMessageId) {
                const updated = { 
                  ...msg, 
                  options: options || msg.options, 
                  content_data: finalContentData || msg.content_data, 
                  isStreaming: false 
                }
                console.log('✅ Final message update:', updated)
                console.log('   Updated content_data:', updated.content_data)
                console.log('   Updated images:', updated.content_data?.images)
                return updated
              }
              return msg
            })
          )
        }
      }

    } catch (error) {
      console.error('Error sending message:', error)
      const errorMessage = error.message || 'An unknown error occurred'
      showError('Failed to send message', errorMessage)
      
      // Try to get more detailed error from response if available
      let detailedError = 'Sorry, I encountered an error. Please try again.'
      if (error.response) {
        try {
          const errorData = await error.response.json()
          detailedError = errorData.detail || errorData.error || errorData.message || detailedError
        } catch (e) {
          // If response isn't JSON, use the status text
          detailedError = error.response.statusText || detailedError
        }
      }
      
      // Update the bot message with error, but preserve existing content if it exists
      setMessages(prev => 
        prev.map(msg => {
          if (msg.id === botMessageId) {
            const existingContent = msg.content || ''
            // Only show error if we don't have any content yet
            // If we have content, the response was successful and we shouldn't show an error
            if (!existingContent || existingContent.trim().length === 0) {
              // No content yet, show error
              return { ...msg, content: detailedError, isStreaming: false }
            } else {
              // We have content, response was successful - don't show error
              // Just log it for debugging
              console.warn('Error occurred but message already has content, not showing error to user:', detailedError)
              return { ...msg, isStreaming: false }
            }
          }
          return msg
        })
      )
    } finally {
      setIsLoading(false)
      setIsStreaming(false)
      // Refocus input after sending message
      setTimeout(() => {
        if (inputRef.current && !isCallActive && !isLoading && !isStreaming && !isModalOpen()) {
        inputRef.current.focus()
      }
      }, 150)
    }
  }

  const getAuthToken = async () => {
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token
  }

  const handleFileUpload = async (file) => {
    if (!file) return

    // Validate file type - support images and videos
    const allowedImageTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
    const allowedVideoTypes = ['video/mp4', 'video/mpeg', 'video/quicktime', 'video/x-msvideo', 'video/webm']
    const allowedTypes = [...allowedImageTypes, ...allowedVideoTypes]
    
    if (!allowedTypes.includes(file.type)) {
      showError("Invalid file type", "Please select a valid image or video file (JPEG, PNG, GIF, WebP, MP4, MOV, AVI, or WebM)")
      return
    }

    // Validate file size (max 50MB for videos, 10MB for images)
    const isVideo = allowedVideoTypes.includes(file.type)
    const maxSize = isVideo ? 50 * 1024 * 1024 : 10 * 1024 * 1024 // 50MB for videos, 10MB for images
    if (file.size > maxSize) {
      showError("File too large", `File size must be less than ${isVideo ? '50MB' : '10MB'}`)
      return
    }

    try {
      setIsLoading(true)
      const authToken = await getAuthToken()
      if (!authToken) {
        showError("Authentication required", "Please log in again.")
        return
      }

      // Upload file to backend
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_BASE_URL}/media/upload-media`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${authToken}`
        },
        body: formData
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(errorData.detail || 'Upload failed')
      }

      const data = await response.json()
      if (data.success && data.url) {
        // Send the uploaded file URL to the chatbot
        // Format: "upload" + the URL so the backend knows it's an upload response
        const messageToSend = `upload ${data.url}`
        setInputMessage(messageToSend)
        setTimeout(() => {
          sendMessage(messageToSend)
        }, 100)
        showSuccess("File uploaded", "Your file has been uploaded successfully.")
      } else {
        throw new Error(data.detail || 'Upload failed')
      }
    } catch (error) {
      console.error('File upload error:', error)
      showError("Upload failed", error.message || "Please try again.")
    } finally {
      setIsLoading(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleFileInputChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      handleFileUpload(file)
    }
  }

  const fetchScheduledMessages = async () => {
    try {
      const authToken = await getAuthToken()
      
      // First, check if messages exist for today
      const response = await fetch(`${API_BASE_URL}/chatbot/scheduled-messages`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        }
      })

      if (response.ok) {
        const data = await response.json()
        console.log('Scheduled messages response:', data)
        
        // If no messages exist for today, generate them
        if (data.success && (!data.messages || data.messages.length === 0)) {
          console.log('No scheduled messages found, generating...')
          try {
            const generateResponse = await fetch(`${API_BASE_URL}/chatbot/scheduled-messages/generate-today`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
              }
            })
            
            if (generateResponse.ok) {
              const generateData = await generateResponse.json()
              if (generateData.success && generateData.messages && generateData.messages.length > 0) {
                // Fetch again to get the newly generated messages
                const newResponse = await fetch(`${API_BASE_URL}/chatbot/scheduled-messages`, {
                  method: 'GET',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                  }
                })
                
                if (newResponse.ok) {
                  const newData = await newResponse.json()
                  if (newData.success && newData.messages && newData.messages.length > 0) {
                    displayScheduledMessages(newData.messages, authToken)
                    return
                  }
                }
              }
            }
          } catch (error) {
            console.error('Error generating today\'s messages:', error)
            // Continue to try displaying any existing messages
          }
        }
        
        // Display existing messages if any
        if (data.success && data.messages && data.messages.length > 0) {
          console.log(`Displaying ${data.messages.length} scheduled messages`)
          displayScheduledMessages(data.messages, authToken)
        } else {
          console.log('No scheduled messages to display')
        }
      }
    } catch (error) {
      console.error('Error fetching scheduled messages:', error)
      // Silently fail - don't show error to user
    }
  }

  const displayScheduledMessages = (messages, authToken) => {
    if (!messages || messages.length === 0) return
    
    setMessages(prev => {
      // Get existing scheduled message IDs from both scheduled messages and conversations
      const existingScheduledIds = new Set()
      prev.forEach(msg => {
        if (msg.scheduledMessageId) {
          existingScheduledIds.add(msg.scheduledMessageId)
        }
      })
      
      // Filter out messages that are already displayed
      const newScheduledMessages = messages.filter(msg => 
        !existingScheduledIds.has(msg.id)
      )
      
      // Only update cache if new messages are being added
      const hasNewMessages = newScheduledMessages.length > 0
      
      if (newScheduledMessages.length === 0) {
        return prev // No new messages to add
      }
      
      // Convert scheduled messages to message format
      const scheduledMessageObjects = newScheduledMessages.map(scheduledMsg => {
        const metadata = scheduledMsg.metadata || {}
        const isChase = metadata.sender === 'chase'
        const isLeo = metadata.sender === 'leo'
        const isEmily = !isChase && !isLeo
        return {
          id: `scheduled-${scheduledMsg.id}`,
          type: 'bot',
          content: scheduledMsg.content,
          timestamp: scheduledMsg.scheduled_time || new Date().toISOString(),
          isNew: true,
          scheduledMessageId: scheduledMsg.id,
          isChase: isChase,
          isLeo: isLeo,
          isEmily: isEmily,
          chaseMetadata: isChase ? {
            leadId: metadata.lead_id,
            leadName: metadata.lead_name,
            emailContent: metadata.email_content,
            emailSubject: metadata.email_subject
          } : null
        }
      })
      
      // Merge with existing messages
      const allMessages = [...prev, ...scheduledMessageObjects]
      
      // Remove duplicates based on scheduledMessageId
      const uniqueMessages = []
      const seenScheduledIds = new Set()
      const seenContentHashes = new Set()
      
      for (const msg of allMessages) {
        // Check by scheduled message ID first (most reliable)
        if (msg.scheduledMessageId) {
          if (seenScheduledIds.has(msg.scheduledMessageId)) {
            continue // Skip duplicate
          }
          seenScheduledIds.add(msg.scheduledMessageId)
          uniqueMessages.push(msg)
          continue
        }
        
        // For non-scheduled messages, check by content and timestamp
        const contentHash = `${msg.content?.substring(0, 200)}_${msg.timestamp?.substring(0, 16)}` // First 200 chars + date part
        if (seenContentHashes.has(contentHash)) {
          continue // Skip duplicate
        }
        seenContentHashes.add(contentHash)
        uniqueMessages.push(msg)
      }
      
      // Sort all messages chronologically by timestamp
      uniqueMessages.sort((a, b) => {
        const timeA = new Date(a.timestamp || 0).getTime()
        const timeB = new Date(b.timestamp || 0).getTime()
        return timeA - timeB
      })
      
      // Update cache when new scheduled messages are added (after deduplication and sorting)
      if (hasNewMessages) {
        saveMessagesToCache(uniqueMessages)
      }
      
      // Remove animation flags after a delay
      setTimeout(() => {
        setMessages(current => current.map(msg => 
          scheduledMessageObjects.some(sm => sm.id === msg.id) && msg.isNew
            ? { ...msg, isNew: false }
            : msg
        ))
      }, 400)
      
      // Mark scheduled messages as delivered (only if not already delivered)
      newScheduledMessages.forEach(scheduledMsg => {
        // Only mark as delivered if it's not already delivered
        if (!scheduledMsg.is_delivered) {
          setTimeout(async () => {
            try {
              await fetch(`${API_BASE_URL}/chatbot/scheduled-messages/${scheduledMsg.id}/deliver`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${authToken}`
                }
              })
            } catch (error) {
              console.error('Error delivering scheduled message:', error)
            }
          }, 100)
        } else {
          console.log(`Message ${scheduledMsg.id} already delivered, skipping deliver call`)
        }
      })
      
      return uniqueMessages
    })
  }

  // Note: Key handling is now done in textarea onKeyDown

  const toggleMessageExpansion = (messageId) => {
    setExpandedMessages(prev => {
      const newSet = new Set(prev)
      if (newSet.has(messageId)) {
        newSet.delete(messageId)
      } else {
        newSet.add(messageId)
      }
      return newSet
    })
  }

  const shouldShowReadMore = (content) => {
    if (!content) return false
    
    // Strip ALL markdown and formatting to get pure text content
    // This ensures we measure actual visible content, not markdown syntax
    const plainText = content
      .replace(/```[\s\S]*?```/g, '') // Remove code blocks (including content)
      .replace(/`[^`]+`/g, '') // Remove inline code
      .replace(/\*\*([^*]+)\*\*/g, '$1') // Remove bold markers, keep text
      .replace(/\*([^*]+)\*/g, '$1') // Remove italic markers, keep text
      .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1') // Remove link syntax, keep text
      .replace(/^#{1,6}\s+/gm, '') // Remove header markers
      .replace(/^[\s]*[-*+]\s+/gm, '') // Remove bullet list markers
      .replace(/^[\s]*\d+\.\s+/gm, '') // Remove numbered list markers
      .replace(/!\[([^\]]*)\]\([^\)]+\)/g, '') // Remove images
      .replace(/^>+\s+/gm, '') // Remove blockquote markers
      .replace(/\n{3,}/g, '\n\n') // Normalize multiple newlines
      .replace(/[ \t]+/g, ' ') // Normalize spaces and tabs
      .trim()
    
    // Count actual visible text characters (pure text, no markdown)
    const textCharCount = plainText.length
    
    // Count line breaks in original content (before markdown stripping)
    const originalLineBreaks = (content.match(/\n/g) || []).length
    
    // Count line breaks in plain text (after stripping)
    const plainTextLineBreaks = (plainText.match(/\n/g) || []).length
    
    // BALANCED: Show "Read more" on longer responses that exceed 8 lines
    // Use reasonable thresholds to catch long messages but avoid short ones
    
    // Method 1: If plain text has 800+ characters, likely exceeds 8 lines
    // (8 lines × ~70-80 chars = 560-640, so 800+ is reasonable for longer content)
    if (textCharCount >= 800) {
      return true
    }
    
    // Method 2: If there are 10+ line breaks AND substantial text (>600 chars)
    // This catches longer structured content with many paragraphs/sections
    if (originalLineBreaks >= 10 && textCharCount > 600) {
      return true
    }
    
    // Method 3: If there are 9+ line breaks in plain text (after stripping)
    // This catches well-structured longer content
    if (plainTextLineBreaks >= 9 && textCharCount > 550) {
      return true
    }
    
    // Lower threshold for testing - if content is clearly longer than 8 lines
    // 8 lines × 70 chars = 560, so anything over 700 should definitely show
    if (textCharCount >= 700) {
      return true
    }
    
    // Otherwise, content is not long enough to need truncation
    return false
  }

  const handleCopyMessage = async (content) => {
    try {
      await navigator.clipboard.writeText(content)
      showSuccess('Message copied to clipboard')
    } catch (error) {
      console.error('Failed to copy:', error)
      showError('Failed to copy message')
    }
  }

  const handleReplyToMessage = (message) => {
    setReplyingToMessage(message)
    setInputMessage('')
    inputRef.current?.focus()
  }

  const handleMicClick = () => {
    if (isListening) {
      // Stop listening
      if (inputRecognitionRef.current) {
        inputRecognitionRef.current.stop()
        setIsListening(false)
      }
      return
    }

    // Check if browser supports speech recognition
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      showError('Speech recognition not supported', 'Your browser does not support speech recognition. Please use Chrome, Edge, or Safari.')
      return
    }

    // Initialize speech recognition
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognition()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onstart = () => {
      setIsListening(true)
    }

    recognition.onresult = (event) => {
      let interimTranscript = ''
      let finalTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          finalTranscript += transcript + ' '
        } else {
          interimTranscript += transcript
        }
      }

      // Update input with interim results
      if (interimTranscript) {
        setInputMessage(finalTranscript + interimTranscript)
      }

      // If we have final results, send the message
      if (finalTranscript.trim()) {
        setInputMessage(finalTranscript.trim())
        recognition.stop()
        setIsListening(false)
        // Send the message after a short delay
        setTimeout(() => {
          sendMessage(finalTranscript.trim())
        }, 100)
      }
    }

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error)
      setIsListening(false)
      
      if (event.error === 'not-allowed') {
        showError('Microphone permission denied', 'Please allow microphone access to use speech-to-text.')
      } else if (event.error === 'no-speech') {
        showError('No speech detected', 'Please try speaking again.')
      } else {
        showError('Speech recognition error', event.error)
      }
    }

    recognition.onend = () => {
      setIsListening(false)
    }

    inputRecognitionRef.current = recognition
    
    try {
      recognition.start()
    } catch (error) {
      console.error('Error starting recognition:', error)
      showError('Failed to start speech recognition', error.message)
      setIsListening(false)
    }
  }

  const handleDeleteMessage = async (message) => {
    if (!message.conversationId) {
      // If it's a local message (not saved to Supabase), just remove from UI
      setMessages(prev => prev.filter(msg => msg.id !== message.id))
      return
    }

    try {
      const authToken = await getAuthToken()
      if (!authToken) {
        throw new Error('No authentication token available')
      }

      const response = await fetch(`${API_BASE_URL}/chatbot/conversations/${message.conversationId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${authToken}`
        }
      })

      if (!response.ok) {
        throw new Error('Failed to delete message')
      }

      // Remove from UI
      setMessages(prev => prev.filter(msg => msg.id !== message.id))
      showSuccess('Message deleted')
    } catch (error) {
      console.error('Error deleting message:', error)
      showError('Failed to delete message')
    }
  }

  const formatTime = (timestamp) => {
    if (!timestamp) return ''
    
    const messageDate = new Date(timestamp)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const messageDay = new Date(messageDate.getFullYear(), messageDate.getMonth(), messageDate.getDate())
    
    // If message is from today, show only time
    if (messageDay.getTime() === today.getTime()) {
      return messageDate.toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit'
      })
    }
    
    // If message is from yesterday, show "Yest.." and time
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    if (messageDay.getTime() === yesterday.getTime()) {
      return `Yest.. ${messageDate.toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit'
      })}`
    }
    
    // Otherwise show date and time
    return messageDate.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit', 
      minute: '2-digit' 
    })
  }

  // Expose loadConversations method via ref
  React.useImperativeHandle(ref, () => ({
    loadConversations: (messages) => {
      setMessages(messages)
      // Don't auto-expand - let users use "Read more" button to expand messages
      // This ensures consistent behavior and the button is always available
      // Scroll to bottom after loading
      setTimeout(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "auto" })
      }, 100)
    },
    clearChat: () => {
      setMessages([])
      setInputMessage('')
      setReplyingToMessage(null)
      // Clear any cached messages
      if (typeof Storage !== 'undefined') {
        try {
          localStorage.removeItem('chatbot_messages_cache')
        } catch (e) {
          console.error('Error clearing message cache:', e)
        }
      }
    },
    startCall: () => {
      // Call already started via useEffect
      console.log('Call started')
    },
    endCall: () => {
      // Stop recognition
      if (recognitionRef.current) {
        isListeningRef.current = false
        try {
          recognitionRef.current.stop()
        } catch (e) {
          console.log('Recognition already stopped')
        }
        recognitionRef.current = null
      }
      // Cancel any ongoing speech
      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
        currentAudioRef.current = null
      }
    }
  }))

  return (
    <div className="flex flex-col bg-white" style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Messages */}
      <div className="flex-1 p-4 space-y-4 messages-container" style={{ overflowY: 'auto', overflowX: 'hidden', minHeight: 0 }}>
        {messages
          .filter(message => {
            if (messageFilter === 'all') return true
            if (messageFilter === 'emily') return message.isEmily
            if (messageFilter === 'chase') return message.isChase
            if (messageFilter === 'leo') return message.isLeo
            return true
          })
          .map((message) => (
          <div
            key={message.id}
            className={`flex flex-col ${message.type === 'user' ? 'items-end' : 'items-start'} w-full px-4 ${message.isNew ? 'animate-slide-in' : ''}`}
          >
            <div className={`flex items-start gap-2 ${message.type === 'user' ? 'justify-end flex-row-reverse ml-auto' : 'justify-start'} max-w-[85%]`}>
              {/* Icon */}
              <div className={`flex-shrink-0 ${message.type === 'user' ? 'order-2' : ''}`}>
                {message.type === 'user' ? (
                  profile?.logo_url ? (
                    <div className="w-5 h-5 md:w-8 md:h-8 rounded-full overflow-hidden backdrop-blur-md bg-pink-500/80 border border-pink-400/30">
                    <img 
                      src={profile.logo_url} 
                      alt="User" 
                        className="w-full h-full object-cover"
                    />
                    </div>
                  ) : (
                    <div className="w-5 h-5 md:w-8 md:h-8 rounded-full backdrop-blur-md bg-pink-500/80 border border-pink-400/30 flex items-center justify-center">
                      <User className="w-3 h-3 md:w-5 md:h-5 text-white" />
                    </div>
                  )
                ) : (
                  <div className={`w-5 h-5 md:w-8 md:h-8 rounded-full flex items-center justify-center shadow-md ${
                    message.isChase 
                      ? 'bg-gradient-to-br from-blue-400 to-blue-600' 
                      : 'bg-gradient-to-br from-pink-400 to-purple-500'
                  }`}>
                    <span className="text-white font-bold text-xs md:text-sm">
                      {message.isChase ? 'C' : message.isLeo ? 'L' : 'E'}
                    </span>
                  </div>
                )}
              </div>
              {/* Message Bubble */}
              <div 
                  className={`px-4 rounded-lg relative group message-bubble backdrop-blur-md ${
                  message.type === 'user'
                      ? 'py-2 bg-pink-500/80 text-white border border-pink-400/30 text-right'
                      : 'py-3 bg-white/70 text-black chatbot-bubble-shadow border border-white/30 text-left'
                }`}
                onMouseEnter={() => setHoveredMessageId(message.id)}
                onMouseLeave={() => setHoveredMessageId(null)}
                onMouseDown={() => {
                  isSelectingTextRef.current = true
                }}
                onMouseUp={() => {
                  // Keep selection flag active if text is selected
                  setTimeout(() => {
                    const selection = window.getSelection()
                    if (selection && selection.toString().length > 0) {
                      isSelectingTextRef.current = true
                      setTimeout(() => {
                        isSelectingTextRef.current = false
                      }, 2000)
                    } else {
                      isSelectingTextRef.current = false
                    }
                  }, 100)
                }}
                style={{ userSelect: 'text', WebkitUserSelect: 'text' }}
              >
                {/* Agent Name - Only show for bot messages, inside bubble at top */}
                {message.type === 'bot' && (
                  <div className="mb-2">
                    <span className="text-base font-semibold text-purple-600">
                      {message.isChase ? 'Chase' : message.isLeo ? 'Leo' : 'Emily'}
                    </span>
                  </div>
                )}
                {/* Hover Actions */}
                {hoveredMessageId === message.id && (
                  <div className={`absolute ${message.type === 'user' ? 'left-0 -left-24' : 'right-0 -right-24'} top-0 flex gap-1 bg-white rounded-lg shadow-lg border border-gray-200 p-1 z-10`}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleCopyMessage(message.content)
                      }}
                      className="p-2 hover:bg-gray-100 rounded transition-colors"
                      title="Copy"
                    >
                      <Copy className="w-4 h-4 text-gray-600" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleReplyToMessage(message)
                      }}
                      className="p-2 hover:bg-gray-100 rounded transition-colors"
                      title="Reply"
                    >
                      <Reply className="w-4 h-4 text-gray-600" />
                    </button>
                  <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (window.confirm('Are you sure you want to delete this message?')) {
                          handleDeleteMessage(message)
                        }
                      }}
                      className="p-2 hover:bg-red-50 rounded transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4 text-red-600" />
                  </button>
              </div>
                )}
                
                {/* Reply Indicator */}
                {message.replyingTo && (
                  <div className={`mb-2 pb-2 border-b ${message.type === 'user' ? 'border-white/30' : 'border-gray-200'}`}>
                    <div className={`text-xs ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                      Replying to: {message.replyingTo.content.substring(0, 50)}...
            </div>
          </div>
        )}
                {(message.content || message.content_data) ? (
                  <div className={`text-sm leading-relaxed prose prose-sm max-w-none ${message.type === 'user' ? 'text-right' : 'text-left'} ${message.content_data ? 'prose-no-bottom-margin' : ''}`}>
                    {/* Special handling for upload messages */}
                    {message.type === 'user' && message.content && message.content.trim().toLowerCase().startsWith('upload ') ? (
                      <div className="flex flex-col items-end gap-2">
                        <span className="text-white">uploaded</span>
                        {(() => {
                          const urlMatch = message.content.match(/upload\s+(https?:\/\/[^\s]+)/i)
                          const imageUrl = urlMatch ? urlMatch[1] : null
                          if (imageUrl) {
                            return (
                              <img
                                src={imageUrl}
                                alt="Uploaded"
                                className="object-cover rounded"
                                style={{ width: '200px', height: '200px' }}
                                onError={(e) => {
                                  e.target.style.display = 'none'
                                }}
                              />
                            )
                          }
                          return null
                        })()}
                      </div>
                    ) : shouldShowReadMore(message.content) && !expandedMessages.has(message.id) ? (
                      <div className="message-content-truncated">
                        <ReactMarkdown 
                          remarkPlugins={[remarkGfm]}
                          components={{
                            p: ({ children }) => <p className={`mb-2 last:mb-0 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</p>,
                            h1: ({ children }) => <h1 className={`text-lg font-bold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h1>,
                            h2: ({ children }) => <h2 className={`text-base font-semibold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h2>,
                            h3: ({ children }) => <h3 className={`text-sm font-semibold mb-1 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h3>,
                            ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                            li: ({ children }) => <li className={message.type === 'user' ? 'text-white' : 'text-black'}>{children}</li>,
                            code: ({ children, className }) => {
                              const isInline = !className?.includes('language-')
                              return isInline ? (
                                <code className={`px-1 py-0.5 rounded text-xs font-mono ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              ) : (
                                <code className={`block p-2 rounded text-xs font-mono overflow-x-auto ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              )
                            },
                            pre: ({ children }) => <pre className={`p-2 rounded text-xs font-mono overflow-x-auto mb-2 ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</pre>,
                            blockquote: ({ children }) => <blockquote className={`border-l-4 pl-3 italic mb-2 ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-400 text-black/80'}`}>{children}</blockquote>,
                            strong: ({ children }) => <strong className={`font-semibold ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</strong>,
                            em: ({ children }) => <em className={`italic ${message.type === 'user' ? 'text-white/90' : 'text-black/80'}`}>{children}</em>,
                            br: () => <br className="block" />,
                            a: ({ children, href }) => {
                              // Handle lead links - navigate to leads dashboard
                              if (href && href.startsWith('leads/')) {
                                const leadId = href.replace('leads/', '')
                                return (
                                  <button
                                    onClick={(e) => {
                                      e.preventDefault()
                                      navigate(`/leads?leadId=${leadId}`)
                                    }}
                                    className={`underline cursor-pointer ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`}
                                  >
                                    {children}
                                  </button>
                                )
                              }
                              // Regular links
                              return (
                                <a 
                                  href={href} 
                                  className={`underline ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`} 
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {children}
                                </a>
                              )
                            },
                            table: ({ children }) => <div className="overflow-x-auto mb-2"><table className={`min-w-full border rounded ${message.type === 'user' ? 'border-white/30' : 'border-purple-300'}`}>{children}</table></div>,
                            th: ({ children }) => <th className={`border px-2 py-1 text-left text-xs font-semibold ${message.type === 'user' ? 'border-white/30 bg-white/10 text-white' : 'border-purple-300 bg-purple-100 text-black'}`}>{children}</th>,
                            td: ({ children }) => <td className={`border px-2 py-1 text-xs ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-300 text-black/90'}`}>{children}</td>,
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div className="message-content-wrapper">
                        <ReactMarkdown 
                          remarkPlugins={[remarkGfm]}
                          components={{
                            p: ({ children }) => (
                              <p className={`mb-2 last:mb-0 message-paragraph message-last-line-wrapper ${message.type === 'user' ? 'text-white' : 'text-black'}`}>
                                <span className="message-text">{children}</span>
                              </p>
                            ),
                            h1: ({ children }) => <h1 className={`text-lg font-bold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h1>,
                            h2: ({ children }) => <h2 className={`text-base font-semibold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h2>,
                            h3: ({ children }) => <h3 className={`text-sm font-semibold mb-1 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h3>,
                            ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                            li: ({ children }) => <li className={message.type === 'user' ? 'text-white' : 'text-black'}>{children}</li>,
                            code: ({ children, className }) => {
                              const isInline = !className?.includes('language-')
                              return isInline ? (
                                <code className={`px-1 py-0.5 rounded text-xs font-mono ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              ) : (
                                <code className={`block p-2 rounded text-xs font-mono overflow-x-auto ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              )
                            },
                            pre: ({ children }) => <pre className={`p-2 rounded text-xs font-mono overflow-x-auto mb-2 ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</pre>,
                            blockquote: ({ children }) => <blockquote className={`border-l-4 pl-3 italic mb-2 ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-400 text-black/80'}`}>{children}</blockquote>,
                            strong: ({ children }) => <strong className={`font-semibold ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</strong>,
                            em: ({ children }) => <em className={`italic ${message.type === 'user' ? 'text-white/90' : 'text-black/80'}`}>{children}</em>,
                            br: () => <br className="block" />,
                            a: ({ children, href }) => {
                              // Handle lead links - navigate to leads dashboard
                              if (href && href.startsWith('leads/')) {
                                const leadId = href.replace('leads/', '')
                                return (
                                  <button
                                    onClick={(e) => {
                                      e.preventDefault()
                                      navigate(`/leads?leadId=${leadId}`)
                                    }}
                                    className={`underline cursor-pointer ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`}
                                  >
                                    {children}
                                  </button>
                                )
                              }
                              // Regular links
                              return (
                                <a 
                                  href={href} 
                                  className={`underline ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`} 
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {children}
                                </a>
                              )
                            },
                            table: ({ children }) => <div className="overflow-x-auto mb-2"><table className={`min-w-full border rounded ${message.type === 'user' ? 'border-white/30' : 'border-purple-300'}`}>{children}</table></div>,
                            th: ({ children }) => <th className={`border px-2 py-1 text-left text-xs font-semibold ${message.type === 'user' ? 'border-white/30 bg-white/10 text-white' : 'border-purple-300 bg-purple-100 text-black'}`}>{children}</th>,
                            td: ({ children }) => <td className={`border px-2 py-1 text-xs ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-300 text-black/90'}`}>{children}</td>,
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                        {message.timestamp && !shouldShowReadMore(message.content) && (
                          <span className={`message-timestamp-bottom-right text-xs ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </div>
                    )}
                    {shouldShowReadMore(message.content) && !expandedMessages.has(message.id) && (
                      <span className="inline">
                        <span 
                          onClick={() => toggleMessageExpansion(message.id)}
                          className={`inline ml-1 cursor-pointer font-medium ${message.type === 'user' ? 'text-pink-300 hover:text-pink-200' : 'text-purple-600 hover:text-purple-700'}`}
                          style={{ textDecoration: 'none' }}
                        >
                          Read more
                        </span>
                        {message.timestamp && (
                          <span className={`ml-2 text-xs inline ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </span>
                    )}
                    {shouldShowReadMore(message.content) && expandedMessages.has(message.id) && (
                      <div className="mt-2">
                        <span 
                          onClick={() => toggleMessageExpansion(message.id)}
                          className={`inline-block cursor-pointer font-medium ${message.type === 'user' ? 'text-pink-300 hover:text-pink-200' : 'text-purple-600 hover:text-purple-700'}`}
                          style={{ textDecoration: 'none' }}
                        >
                          Read less
                        </span>
                        {message.timestamp && (
                          <span className={`ml-3 text-xs ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </div>
                    )}
                    
                    {/* Email Content Box for Chase Messages */}
                    {message.isChase && message.chaseMetadata && message.chaseMetadata.emailContent && (
                      <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
                        <button
                          onClick={() => {
                            setExpandedEmailBoxes(prev => {
                              const newSet = new Set(prev)
                              if (newSet.has(message.id)) {
                                newSet.delete(message.id)
                              } else {
                                newSet.add(message.id)
                              }
                              return newSet
                            })
                          }}
                          className="w-full px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left flex items-center justify-between"
                        >
                          <div className="flex-1">
                            <div className="text-xs font-semibold text-gray-700 mb-1">
                              {message.chaseMetadata.emailSubject || 'Email Content'}
                            </div>
                            {!expandedEmailBoxes.has(message.id) && (
                              <div className="text-xs text-gray-500 line-clamp-3">
                                {message.chaseMetadata.emailContent.replace(/<[^>]*>/g, '').substring(0, 150)}...
                              </div>
                            )}
                          </div>
                          <span className="text-xs text-gray-500 ml-2">
                            {expandedEmailBoxes.has(message.id) ? '▼' : '▶'}
                          </span>
                        </button>
                        {expandedEmailBoxes.has(message.id) && (
                          <div className="px-3 py-2 bg-white border-t border-gray-200">
                            <div 
                              className="text-xs text-gray-700 prose prose-sm max-w-none"
                              dangerouslySetInnerHTML={{ __html: message.chaseMetadata.emailContent }}
                            />
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* Clickable Options */}
                    {/* Social Media Post Card */}
                    {message.content_data && (
                      <div className="mt-3 max-w-lg" style={{ transform: 'scale(0.84)', transformOrigin: 'left top', marginBottom: '-20%' }}>
                        <div className="bg-white rounded-lg border border-gray-200 shadow-lg overflow-hidden">
                          {/* Post Header */}
                          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
                            <div className="flex items-center space-x-3">
                              {(() => {
                                const platform = message.content_data.platform?.toLowerCase() || ''
                                const getPlatformIcon = () => {
                                  if (platform.includes('instagram')) {
                                    return <Instagram className="w-6 h-6 md:w-10 md:h-10 text-pink-600" />
                                  } else if (platform.includes('facebook')) {
                                    return <Facebook className="w-6 h-6 md:w-10 md:h-10 text-blue-600" />
                                  } else if (platform.includes('linkedin')) {
                                    return <Linkedin className="w-6 h-6 md:w-10 md:h-10 text-blue-700" />
                                  } else if (platform.includes('youtube')) {
                                    return <Youtube className="w-6 h-6 md:w-10 md:h-10 text-red-600" />
                                  } else if (platform.includes('twitter') || platform.includes('x')) {
                                    return <Twitter className="w-6 h-6 md:w-10 md:h-10 text-black" />
                                  } else if (platform.includes('pinterest')) {
                                    return (
                                      <svg className="w-6 h-6 md:w-10 md:h-10 text-red-600" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.49-.09-.79-.17-2.01.03-2.87.18-.78 1.16-4.97 1.16-4.97s-.3-.6-.3-1.48c0-1.38.8-2.41 1.8-2.41.85 0 1.26.64 1.26 1.4 0 .85-.54 2.12-.82 3.3-.23.94.48 1.7 1.42 1.7 1.71 0 3.02-1.8 3.02-4.4 0-2.3-1.67-3.91-4.05-3.91-2.76 0-4.38 2.07-4.38 4.2 0 .82.32 1.7.72 2.19.08.1.09.19.07.29l-.28 1.12c-.04.16-.13.2-.3.12-1.12-.52-1.82-2.15-1.82-3.46 0-2.83 2.06-5.43 5.94-5.43 3.12 0 5.54 2.22 5.54 5.19 0 3.1-1.95 5.59-4.73 5.59-.93 0-1.8-.48-2.1-1.18l-.57 2.18c-.21.81-.78 1.83-1.16 2.45 1.19.37 2.45.57 3.78.57 5.52 0 10-4.48 10-10S17.52 2 12 2z"/>
                                      </svg>
                                    )
                                  } else {
                                    return (
                                      <div className="w-6 h-6 md:w-10 md:h-10 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-xs md:text-sm">
                                        {platform ? platform.charAt(0).toUpperCase() : 'AI'}
                                      </div>
                                    )
                                  }
                                }
                                return (
                                  <div className="flex items-center justify-center">
                                    {getPlatformIcon()}
                                  </div>
                                )
                              })()}
                              <div>
                                <div className="font-semibold text-gray-900 text-sm">
                                  {message.content_data.platform ? 
                                    message.content_data.platform.charAt(0).toUpperCase() + message.content_data.platform.slice(1) : 
                                    'AI Content'
                                  }
                                </div>
                                <div className="text-xs text-gray-500">
                                  {message.content_data.content_type ? 
                                    message.content_data.content_type.charAt(0).toUpperCase() + message.content_data.content_type.slice(1) : 
                                    'Post'
                                  }
                                </div>
                              </div>
                            </div>
                            <button className="p-1 hover:bg-gray-100 rounded-full transition-colors">
                              <MoreHorizontal className="w-5 h-5 text-gray-600" />
                            </button>
                          </div>

                          {/* Post Images */}
                          {message.content_data.images && 
                           Array.isArray(message.content_data.images) && 
                           message.content_data.images.length > 0 && (
                            <div className="relative">
                              {message.content_data.images.length === 1 ? (
                                <img
                                  src={message.content_data.images[0]}
                                  alt="Post content"
                                  className="w-full h-auto object-cover"
                                  onError={(e) => {
                                    console.error('❌ Failed to load image:', message.content_data.images[0])
                                    e.target.style.display = 'none'
                                  }}
                                />
                              ) : (
                                <div className="grid grid-cols-2 gap-0">
                                  {message.content_data.images.slice(0, 4).map((imageUrl, index) => (
                                    <div key={index} className="relative aspect-square">
                                      <img
                                        src={imageUrl}
                                        alt={`Post content ${index + 1}`}
                                        className="w-full h-full object-cover"
                                        onError={(e) => {
                                          console.error('❌ Failed to load image:', imageUrl)
                                          e.target.style.display = 'none'
                                        }}
                                      />
                                      {index === 3 && message.content_data.images.length > 4 && (
                                        <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center text-white font-bold text-xl">
                                          +{message.content_data.images.length - 4}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}

                          {/* Post Actions */}
                          <div className="px-4 py-3 border-b border-gray-200">
                            <div className="flex items-center space-x-4">
                              <button className="hover:opacity-70 transition-opacity">
                                <Heart className="w-6 h-6 text-gray-800" />
                              </button>
                              <button className="hover:opacity-70 transition-opacity">
                                <MessageCircle className="w-6 h-6 text-gray-800" />
                              </button>
                              <button className="hover:opacity-70 transition-opacity">
                                <Share2 className="w-6 h-6 text-gray-800" />
                              </button>
                              <div className="flex-1" />
                              <button className="hover:opacity-70 transition-opacity">
                                <Bookmark className="w-6 h-6 text-gray-800" />
                              </button>
                            </div>
                          </div>

                          {/* Post Content */}
                          <div className="px-4 py-3 space-y-2">
                            {/* Title */}
                            {message.content_data.title && (
                              <h3 className="font-bold text-gray-900 text-base">
                                {message.content_data.title}
                              </h3>
                            )}
                            
                            {/* Content Text */}
                            {message.content_data.content && (
                              <div className="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap">
                                {message.content_data.content}
                              </div>
                            )}

                            {/* Hashtags */}
                            {message.content_data.hashtags && 
                             Array.isArray(message.content_data.hashtags) && 
                             message.content_data.hashtags.length > 0 && (
                              <div className="flex flex-wrap gap-2 pt-2">
                                {message.content_data.hashtags.map((tag, index) => {
                                  const cleanTag = tag.replace('#', '')
                                  return (
                                    <span
                                      key={index}
                                      className="text-blue-600 hover:text-blue-800 text-sm font-medium cursor-pointer"
                                    >
                                      #{cleanTag}
                                    </span>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                    
                    {message.options && Array.isArray(message.options) && message.options.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.options.map((option, index) => (
                          <button
                            key={index}
                            onClick={async (e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              
                              // Special handling for "upload" option
                              if (option.toLowerCase() === "upload") {
                                // Trigger file input
                                fileInputRef.current?.click()
                                return
                              }
                              
                              // Set the input message and send it
                              setInputMessage(option)
                              // Small delay to ensure state is updated
                              setTimeout(() => {
                                sendMessage(option)
                                // Refocus input after sending
                                setTimeout(() => {
                                  if (inputRef.current && !isCallActive && !isLoading && !isStreaming) {
                                    inputRef.current.focus()
                                  }
                                }, 200)
                              }, 100)
                            }}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                              message.type === 'user'
                                ? 'bg-white/20 text-white border border-white/30 hover:bg-white/30'
                                : 'bg-purple-100 text-purple-700 border border-purple-200 hover:bg-purple-200'
                            }`}
                          >
                            {option.charAt(0).toUpperCase() + option.slice(1)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : message.isStreaming ? (
                  <div className={`thinking-shimmer ${message.type === 'user' ? 'text-white' : 'text-gray-600'}`}>
                    thinking...
                  </div>
                ) : (
                  <div className="text-sm leading-relaxed prose prose-sm max-w-none">
                    {shouldShowReadMore(message.content) && !expandedMessages.has(message.id) ? (
                      <div className="message-content-truncated">
                        <ReactMarkdown 
                          remarkPlugins={[remarkGfm]}
                          components={{
                            p: ({ children }) => <p className={`mb-2 last:mb-0 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</p>,
                            h1: ({ children }) => <h1 className={`text-lg font-bold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h1>,
                            h2: ({ children }) => <h2 className={`text-base font-semibold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h2>,
                            h3: ({ children }) => <h3 className={`text-sm font-semibold mb-1 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h3>,
                            ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                            li: ({ children }) => <li className={message.type === 'user' ? 'text-white' : 'text-black'}>{children}</li>,
                            code: ({ children, className }) => {
                              const isInline = !className?.includes('language-')
                              return isInline ? (
                                <code className={`px-1 py-0.5 rounded text-xs font-mono ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              ) : (
                                <code className={`block p-2 rounded text-xs font-mono overflow-x-auto ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              )
                            },
                            pre: ({ children }) => <pre className={`p-2 rounded text-xs font-mono overflow-x-auto mb-2 ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</pre>,
                            blockquote: ({ children }) => <blockquote className={`border-l-4 pl-3 italic mb-2 ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-400 text-black/80'}`}>{children}</blockquote>,
                            strong: ({ children }) => <strong className={`font-semibold ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</strong>,
                            em: ({ children }) => <em className={`italic ${message.type === 'user' ? 'text-white/90' : 'text-black/80'}`}>{children}</em>,
                            br: () => <br className="block" />,
                            a: ({ children, href }) => {
                              // Handle lead links - navigate to leads dashboard
                              if (href && href.startsWith('leads/')) {
                                const leadId = href.replace('leads/', '')
                                return (
                                  <button
                                    onClick={(e) => {
                                      e.preventDefault()
                                      navigate(`/leads?leadId=${leadId}`)
                                    }}
                                    className={`underline cursor-pointer ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`}
                                  >
                                    {children}
                                  </button>
                                )
                              }
                              // Regular links
                              return (
                                <a 
                                  href={href} 
                                  className={`underline ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`} 
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {children}
                                </a>
                              )
                            },
                            table: ({ children }) => <div className="overflow-x-auto mb-2"><table className={`min-w-full border rounded ${message.type === 'user' ? 'border-white/30' : 'border-purple-300'}`}>{children}</table></div>,
                            th: ({ children }) => <th className={`border px-2 py-1 text-left text-xs font-semibold ${message.type === 'user' ? 'border-white/30 bg-white/10 text-white' : 'border-purple-300 bg-purple-100 text-black'}`}>{children}</th>,
                            td: ({ children }) => <td className={`border px-2 py-1 text-xs ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-300 text-black/90'}`}>{children}</td>,
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div className="message-content-wrapper">
                        <ReactMarkdown 
                          remarkPlugins={[remarkGfm]}
                          components={{
                            p: ({ children }) => (
                              <p className={`mb-2 last:mb-0 message-paragraph message-last-line-wrapper ${message.type === 'user' ? 'text-white' : 'text-black'}`}>
                                <span className="message-text">{children}</span>
                              </p>
                            ),
                            h1: ({ children }) => <h1 className={`text-lg font-bold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h1>,
                            h2: ({ children }) => <h2 className={`text-base font-semibold mb-2 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h2>,
                            h3: ({ children }) => <h3 className={`text-sm font-semibold mb-1 ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</h3>,
                            ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                            li: ({ children }) => <li className={message.type === 'user' ? 'text-white' : 'text-black'}>{children}</li>,
                            code: ({ children, className }) => {
                              const isInline = !className?.includes('language-')
                              return isInline ? (
                                <code className={`px-1 py-0.5 rounded text-xs font-mono ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              ) : (
                                <code className={`block p-2 rounded text-xs font-mono overflow-x-auto ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</code>
                              )
                            },
                            pre: ({ children }) => <pre className={`p-2 rounded text-xs font-mono overflow-x-auto mb-2 ${message.type === 'user' ? 'bg-white/20 text-white' : 'bg-purple-300 text-black'}`}>{children}</pre>,
                            blockquote: ({ children }) => <blockquote className={`border-l-4 pl-3 italic mb-2 ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-400 text-black/80'}`}>{children}</blockquote>,
                            strong: ({ children }) => <strong className={`font-semibold ${message.type === 'user' ? 'text-white' : 'text-black'}`}>{children}</strong>,
                            em: ({ children }) => <em className={`italic ${message.type === 'user' ? 'text-white/90' : 'text-black/80'}`}>{children}</em>,
                            br: () => <br className="block" />,
                            a: ({ children, href }) => {
                              // Handle lead links - navigate to leads dashboard
                              if (href && href.startsWith('leads/')) {
                                const leadId = href.replace('leads/', '')
                                return (
                                  <button
                                    onClick={(e) => {
                                      e.preventDefault()
                                      navigate(`/leads?leadId=${leadId}`)
                                    }}
                                    className={`underline cursor-pointer ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`}
                                  >
                                    {children}
                                  </button>
                                )
                              }
                              // Regular links
                              return (
                                <a 
                                  href={href} 
                                  className={`underline ${message.type === 'user' ? 'text-white hover:text-white/80' : 'text-purple-700 hover:text-purple-800'}`} 
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {children}
                                </a>
                              )
                            },
                            table: ({ children }) => <div className="overflow-x-auto mb-2"><table className={`min-w-full border rounded ${message.type === 'user' ? 'border-white/30' : 'border-purple-300'}`}>{children}</table></div>,
                            th: ({ children }) => <th className={`border px-2 py-1 text-left text-xs font-semibold ${message.type === 'user' ? 'border-white/30 bg-white/10 text-white' : 'border-purple-300 bg-purple-100 text-black'}`}>{children}</th>,
                            td: ({ children }) => <td className={`border px-2 py-1 text-xs ${message.type === 'user' ? 'border-white/30 text-white/90' : 'border-purple-300 text-black/90'}`}>{children}</td>,
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                        {message.timestamp && !shouldShowReadMore(message.content) && (
                          <span className={`message-timestamp-bottom-right text-xs ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </div>
                    )}
                    {shouldShowReadMore(message.content) && !expandedMessages.has(message.id) && (
                      <span className="inline">
                        <span 
                          onClick={() => toggleMessageExpansion(message.id)}
                          className={`inline ml-1 cursor-pointer font-medium ${message.type === 'user' ? 'text-pink-300 hover:text-pink-200' : 'text-purple-600 hover:text-purple-700'}`}
                          style={{ textDecoration: 'none' }}
                        >
                          Read more
                        </span>
                        {message.timestamp && (
                          <span className={`ml-2 text-xs inline ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </span>
                    )}
                    {shouldShowReadMore(message.content) && expandedMessages.has(message.id) && (
                      <div className="mt-2">
                        <span 
                          onClick={() => toggleMessageExpansion(message.id)}
                          className={`inline-block cursor-pointer font-medium ${message.type === 'user' ? 'text-pink-300 hover:text-pink-200' : 'text-purple-600 hover:text-purple-700'}`}
                          style={{ textDecoration: 'none' }}
                        >
                          Read less
                        </span>
                        {message.timestamp && (
                          <span className={`ml-3 text-xs ${message.type === 'user' ? 'text-white/70' : 'text-gray-500'}`}>
                            {formatTime(message.timestamp)}
                          </span>
                        )}
                      </div>
                    )}
                    
                    {/* Email Content Box for Chase Messages */}
                    {message.isChase && message.chaseMetadata && message.chaseMetadata.emailContent && (
                      <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
                        <button
                          onClick={() => {
                            setExpandedEmailBoxes(prev => {
                              const newSet = new Set(prev)
                              if (newSet.has(message.id)) {
                                newSet.delete(message.id)
                              } else {
                                newSet.add(message.id)
                              }
                              return newSet
                            })
                          }}
                          className="w-full px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left flex items-center justify-between"
                        >
                          <div className="flex-1">
                            <div className="text-xs font-semibold text-gray-700 mb-1">
                              {message.chaseMetadata.emailSubject || 'Email Content'}
                            </div>
                            {!expandedEmailBoxes.has(message.id) && (
                              <div className="text-xs text-gray-500 line-clamp-3">
                                {message.chaseMetadata.emailContent.replace(/<[^>]*>/g, '').substring(0, 150)}...
                              </div>
                            )}
                          </div>
                          <span className="text-xs text-gray-500 ml-2">
                            {expandedEmailBoxes.has(message.id) ? '▼' : '▶'}
                          </span>
                        </button>
                        {expandedEmailBoxes.has(message.id) && (
                          <div className="px-3 py-2 bg-white border-t border-gray-200">
                            <div 
                              className="text-xs text-gray-700 prose prose-sm max-w-none"
                              dangerouslySetInnerHTML={{ __html: message.chaseMetadata.emailContent }}
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {isLoading && !isStreaming && (
          <div className="flex justify-start w-full px-4">
            <div className="bg-white/70 backdrop-blur-md rounded-lg px-4 py-3 chatbot-bubble-shadow border border-white/30">
              <div className="thinking-shimmer text-gray-600">
                thinking...
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input - Fixed at bottom */}
      <div className="bg-transparent px-4 border-t border-white/20 z-10" style={{ 
        flexShrink: 0,
        flexGrow: 0,
        paddingTop: '12px',
        paddingBottom: '12px'
      }}>
        <div className="w-full">
          <div className="relative">
            <div className="relative w-full">
              {replyingToMessage && (
                <div className="absolute left-4 top-2 text-xs text-purple-600 bg-purple-50 px-2 py-1 rounded flex items-center gap-2 z-10">
                  <span>Replying to: {replyingToMessage.content.substring(0, 40)}...</span>
                  <button
                    onClick={() => setReplyingToMessage(null)}
                    className="text-purple-400 hover:text-purple-600 font-bold"
                  >
                    ×
                  </button>
                </div>
              )}
              <textarea
                ref={inputRef}
                value={inputMessage}
                onChange={(e) => {
                  setInputMessage(e.target.value)
                  // Auto-resize textarea
                  e.target.style.height = 'auto'
                  const lineHeight = 24 // Approximate line height in pixels
                  const maxHeight = lineHeight * 4 // 4 rows max
                  const newHeight = Math.min(e.target.scrollHeight, maxHeight)
                  e.target.style.height = `${newHeight}px`
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    sendMessage()
                  }
                }}
                onBlur={(e) => {
                  // IMMEDIATELY refocus - NO RESTRICTIONS
                  if (!isCallActive && !isLoading && !isStreaming && inputRef.current) {
                    // Strategy 1: Immediate synchronous focus
                    inputRef.current.focus()
                    
                    // Strategy 2: requestAnimationFrame for next frame
                    requestAnimationFrame(() => {
                      if (inputRef.current) {
                        inputRef.current.focus()
                      }
                    })
                    
                    // Strategy 3: setTimeout as backup
                    setTimeout(() => {
                      if (inputRef.current && document.activeElement !== inputRef.current) {
                        inputRef.current.focus()
                      }
                    }, 10)
                  }
                }}
                placeholder={replyingToMessage ? `Replying to: ${replyingToMessage.content.substring(0, 30)}...` : "Ask Emily..."}
                className={`w-full py-4 bg-white/70 backdrop-blur-md border border-white/30 rounded-2xl focus:ring-0 focus:border-white/50 outline-none text-sm ${onRefreshChat ? 'pl-36 pr-20' : 'px-6 pr-20'} placeholder:text-gray-500 resize-none overflow-y-auto shadow-lg ${replyingToMessage ? 'pt-8' : ''}`}
                style={{ 
                  minHeight: '56px', 
                  maxHeight: '96px',
                  boxShadow: '0 4px 16px 0 rgba(31, 38, 135, 0.25)'
                }}
                // 1 row min, 4 rows max (24px * 4 = 96px)
                disabled={isLoading || isStreaming}
                rows={1}
                autoFocus
              />
            </div>
            {/* Left side - New Chat button */}
            {onRefreshChat && (
              <div className="absolute left-3 top-1/2 -translate-y-1/2" style={{ marginRight: '8px' }}>
                <button 
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    onRefreshChat()
                  }}
                  disabled={isLoading || isStreaming}
                  className="px-3 py-1.5 text-purple-500 hover:text-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5 text-xs font-medium rounded-md border border-purple-300 hover:bg-purple-50"
                  title="New Chat - Reset conversation and clear intent state"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>New Chat</span>
                </button>
              </div>
            )}
            {/* Right side - Microphone and Send buttons */}
            <div className="absolute right-3 bottom-3 flex items-center space-x-2">
              <button 
                onClick={handleMicClick}
                disabled={isLoading || isStreaming}
                className={`p-2 transition-colors ${
                  isListening 
                    ? 'text-red-500 hover:text-red-700 animate-pulse' 
                    : 'text-purple-500 hover:text-purple-700'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
                title={isListening ? 'Stop listening' : 'Start voice input'}
              >
                <Mic className="w-5 h-5" />
              </button>
              <button
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  if (inputMessage.trim() && !isLoading && !isStreaming) {
                    sendMessage()
                  }
                }}
                disabled={!inputMessage.trim() || isLoading || isStreaming}
                className="p-2 text-purple-500 hover:text-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                type="button"
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>
      
      {/* Hidden file input for media uploads */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,video/mp4,video/mpeg,video/quicktime,video/x-msvideo,video/webm"
        onChange={handleFileInputChange}
        style={{ display: 'none' }}
      />
      
      <style>{`
        @keyframes shimmer {
          0% {
            left: -100%;
          }
          100% {
            left: 100%;
          }
        }
        
        .thinking-shimmer {
          position: relative;
          display: inline-block;
          font-size: 0.875rem;
          font-weight: 500;
          font-style: italic;
          letter-spacing: 0.05em;
          overflow: hidden;
        }
        
        .thinking-shimmer::before {
          content: '';
          position: absolute;
          top: 0;
          left: -100%;
          width: 50%;
          height: 100%;
          background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 1),
            transparent
          );
          animation: shimmer 2s infinite;
        }
        
        .thinking-shimmer.text-white::before {
          background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 1),
            transparent
          );
        }
        
        .thinking-shimmer.text-gray-600::before {
          background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 1),
            transparent
          );
        }
        
        @keyframes slide-in {
          0% {
            opacity: 0;
            transform: translateY(10px);
          }
          100% { 
            opacity: 1;
            transform: translateY(0);
          }
        }
        
        .animate-slide-in {
          animation: slide-in 0.4s ease-out;
        }
        
        .messages-container {
          scrollbar-width: none; /* Firefox */
          -ms-overflow-style: none; /* IE and Edge */
        }
        
        .messages-container::-webkit-scrollbar {
          display: none; /* Chrome, Safari, Opera */
        }
        
        .chatbot-bubble-shadow {
          box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        }
        
        .prose-no-bottom-margin p:last-child {
          margin-bottom: 0 !important;
        }
        
        .line-clamp-3 {
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        
        .message-content-truncated {
          display: -webkit-box;
          -webkit-line-clamp: 8;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        
        .message-content-wrapper {
          position: relative;
          width: 100%;
        }
        
        .message-content-wrapper .message-paragraph:last-of-type {
          margin-bottom: 0;
          padding-right: 5rem;
          position: relative;
        }
        
        .message-timestamp-bottom-right {
          position: absolute;
          bottom: 0;
          right: 0;
          white-space: nowrap;
          line-height: 1.5;
          vertical-align: baseline;
        }
      `}</style>
    </div>
  )
})

export default Chatbot

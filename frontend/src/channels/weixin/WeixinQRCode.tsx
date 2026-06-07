/**
 * WeChat QR Code component - simplified inline version.
 *
 * Displays QR code with 120s auto-refresh.
 * On confirmed login, automatically logs in and navigates to WebUI.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Loader2, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { writeToUrl } from '@/features/chat/utils';

const QRCODE_TIMEOUT = 120; // seconds

type LoginState = 'connecting' | 'waiting' | 'scaned' | 'confirmed' | 'error' | 'expired';

interface WeixinQRCodeProps {
  onLoginSuccess?: () => void;
}

export function WeixinQRCode({ onLoginSuccess }: WeixinQRCodeProps) {
  useAuth();
  const [state, setState] = useState<LoginState>('connecting');
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timeLeft, setTimeLeft] = useState(QRCODE_TIMEOUT);

  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isEffectStaleRef = useRef(false);

  // Clear timer
  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Start countdown timer
  const startTimer = useCallback(() => {
    clearTimer();
    setTimeLeft(QRCODE_TIMEOUT);
    timerRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          clearTimer();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [clearTimer]);

  // Handle confirmed login - directly login without dialog
  const handleConfirmed = useCallback((token: string, userId: string) => {
    setState('confirmed');
    clearTimer();

    // Set cookie and navigate directly
    document.cookie = `agenthub_token=${token}; path=/; max-age=${60 * 60 * 24 * 7}; SameSite=Lax`;
    writeToUrl(userId, null);
    onLoginSuccess?.();
    window.location.reload();
  }, [clearTimer, onLoginSuccess]);

  // Close WebSocket safely - only close if OPEN or forced
  const closeWebSocket = useCallback((force: boolean = false) => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (!wsRef.current) return;

    const ws = wsRef.current;
    const readyState = ws.readyState;

    if (readyState === WebSocket.OPEN) {
      console.log('[WeChat] Closing open WebSocket connection');
      wsRef.current = null;
      ws.close(1000, 'Component cleanup');
    } else if (readyState === WebSocket.CONNECTING) {
      if (force) {
        console.log('[WeChat] Force closing connecting WebSocket');
        wsRef.current = null;
        ws.close(1000, 'Force cleanup');
      } else {
        console.log('[WeChat] Keeping CONNECTING WebSocket for reuse');
      }
    } else {
      wsRef.current = null;
    }
  }, []);

  // Connect WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log('[WeChat] Reusing existing open WebSocket connection');
      return;
    }

    if (wsRef.current && wsRef.current.readyState === WebSocket.CONNECTING) {
      console.log('[WeChat] Connection already in progress, waiting...');
      return;
    }

    setState('connecting');
    setError(null);

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/weixin/auth`;

    console.log('[WeChat] Connecting to:', wsUrl);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WeChat] WebSocket connected successfully');
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        console.log('[WeChat] Received:', msg);

        switch (msg.type) {
          case 'qrcode':
            setQrCodeUrl(msg.qrcode_img);
            setState('waiting');
            startTimer();
            break;

          case 'scaned':
            setState('scaned');
            break;

          case 'confirmed':
            handleConfirmed(msg.token, msg.user_id);
            break;

          case 'expired':
            setState('expired');
            setError('二维码已过期');
            clearTimer();
            break;

          case 'error':
            setState('error');
            setError(msg.message);
            clearTimer();
            break;
        }
      } catch (e) {
        console.error('[WeChat] Parse error:', e);
      }
    };

    ws.onerror = (e) => {
      console.error('[WeChat] WebSocket error:', e);
      setState('error');
      setError('连接失败，请检查后端服务是否启动');
    };

    ws.onclose = (e) => {
      console.log('[WeChat] WebSocket closed:', e.code, e.reason);
      wsRef.current = null;
    };
  }, [startTimer, handleConfirmed, clearTimer]);

  // Reconnect on expire/error - force close and reconnect
  const handleRetry = useCallback(() => {
    closeWebSocket(true);
    reconnectTimeoutRef.current = setTimeout(() => {
      connectWebSocket();
    }, 100);
  }, [closeWebSocket, connectWebSocket]);

  // Auto-reconnect when timer reaches 0
  useEffect(() => {
    if (timeLeft === 0 && state === 'waiting') {
      handleRetry();
    }
  }, [timeLeft, state, handleRetry]);

  // Main effect - connect on mount, with deferred cleanup for StrictMode
  useEffect(() => {
    console.log('[WeChat] Main useEffect running');
    isEffectStaleRef.current = false;

    if (!wsRef.current || wsRef.current.readyState >= WebSocket.CLOSING) {
      connectWebSocket();
    } else {
      console.log('[WeChat] Reusing existing connection, readyState:', wsRef.current.readyState);
    }

    return () => {
      console.log('[WeChat] Main useEffect cleanup');
      isEffectStaleRef.current = true;

      setTimeout(() => {
        if (isEffectStaleRef.current) {
          console.log('[WeChat] Deferred cleanup executing');
          clearTimer();
          closeWebSocket(false);
        } else {
          console.log('[WeChat] Cleanup cancelled (StrictMode remount)');
        }
      }, 50);
    };
  }, [connectWebSocket, clearTimer, closeWebSocket]);

  return (
    <div className="flex flex-col items-center">
      <div className="relative bg-white p-3 rounded-lg border shadow-sm">
        {state === 'connecting' && (
          <div className="w-40 h-40 flex items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {(state === 'waiting' || state === 'scaned') && qrCodeUrl && (
          <>
            <img
              src={qrCodeUrl}
              alt="WeChat QR Code"
              className="w-40 h-40 object-contain"
            />
            {state === 'scaned' && (
              <div className="absolute inset-0 bg-background/80 flex items-center justify-center rounded-lg">
                <div className="text-center">
                  <CheckCircle className="h-10 w-10 text-green-500 mx-auto" />
                  <p className="mt-1 text-sm font-medium">已扫描</p>
                  <p className="text-xs text-muted-foreground">请在手机确认</p>
                </div>
              </div>
            )}
          </>
        )}

        {state === 'confirmed' && (
          <div className="w-40 h-40 flex flex-col items-center justify-center">
            <CheckCircle className="h-10 w-10 text-green-500 mb-2" />
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
          </div>
        )}

        {(state === 'error' || state === 'expired') && (
          <div className="w-40 h-40 flex flex-col items-center justify-center">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="mt-2 text-xs text-muted-foreground">{error}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={handleRetry}>
              <RefreshCw className="h-3 w-3 mr-1" />
              刷新
            </Button>
          </div>
        )}
      </div>

      <div className="mt-3 text-center">
        {state === 'waiting' && timeLeft > 0 && (
          <p className="text-xs text-muted-foreground">
            扫码登录 · {timeLeft}秒后刷新
          </p>
        )}
        {state === 'scaned' && (
          <p className="text-xs text-muted-foreground">请在手机上点击确认</p>
        )}
        {state === 'connecting' && (
          <p className="text-xs text-muted-foreground">正在获取二维码...</p>
        )}
        {state === 'confirmed' && (
          <p className="text-xs text-muted-foreground">&nbsp;</p>
        )}
      </div>
    </div>
  );
}
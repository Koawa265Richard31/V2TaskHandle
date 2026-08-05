export type AgentType = 'a2a' | 'codex' | 'local';
export type AgentStatus = 'online' | 'offline' | 'busy';

export interface AgentInfo {
  type: AgentType;
  name: string;
  status: AgentStatus;
  capabilities: string[];
}

export type TaskStatus = 'pending' | 'ready' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'canceled';

export type ApprovalMode = 'ask' | 'auto' | 'full';

export interface SubTask {
  task_id: string;
  description: string;
  agent_type: AgentType;
  agent_target: string;
  dependencies: string[];
  status: TaskStatus;
  result: string | null;
  error: string | null;
  approval_mode?: ApprovalMode;
  progress?: string | null;
  requires_monitor?: boolean;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  is_streaming: boolean;
  plan: SubTask[] | null;
}

export type SSEEvent =
  | { type: 'plan'; tasks: SubTask[] }
  | { type: 'task_start'; task_id: string; agent_type: AgentType; approval_mode?: ApprovalMode; requires_monitor?: boolean }
  | { type: 'task_update'; task_id: string; status: TaskStatus; progress?: string | null; approval_mode?: ApprovalMode }
  | { type: 'task_progress'; task_id: string; progress: string }
  | { type: 'task_waiting_approval'; task_id: string; message: string; approval_mode?: ApprovalMode }
  | { type: 'task_complete'; task_id: string; result: string; progress?: string | null }
  | { type: 'task_fail'; task_id: string; error: string; progress?: string | null }
  | { type: 'message'; delta: string }
  | { type: 'message_end' }
  | { type: 'done'; final_response: string | null; session_id?: string }
  | { type: 'error'; message: string }
  | { type: 'agent_status'; agent_type: AgentType; status: AgentStatus };

export interface ChatRequest {
  message: string;
  session_id: string | null;
}

// ── 注册中心(云端 PT 协作) ──

export interface Peer {
  id: number;
  name: string;
  url: string;
  role: 'leader' | 'member';
  description?: string;
}

export interface ApprovedPeer {
  request_id: number;
  peer_id: number;
  name: string;
  url: string;
}

export interface JoinRequest {
  id: number;
  peer_id: number;
  peer_name: string;
  peer_url: string;
  leader_id: number;
  status: 'pending' | 'approved' | 'rejected';
  created_at: number;
  decided_at?: number | null;
}

export interface RegistryStatus {
  registered: boolean;
  peer_id: number | null;
  role: 'leader' | 'member';
  name: string;
  registry_url: string;
  approved_peers: ApprovedPeer[];
  requests: JoinRequest[];
}

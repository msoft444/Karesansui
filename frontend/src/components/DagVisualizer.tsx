"use client";

import ReactFlow, {
  Background,
  Controls,
  Edge,
  Handle,
  MarkerType,
  MiniMap,
  Node,
  NodeProps,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A single task node as emitted by the Planner's DAG JSON payload.
 * `status` is injected by the caller based on live execution data.
 */
export type DagNodeStatus = "pending" | "running" | "completed" | "failed";

export interface DagTask {
  task_id: string;
  task_type: "Standard" | "Debate";
  role: string | null;
  participants?: string[];
  mediator?: string | null;
  parent_ids: string[];
  dynamic_params?: Record<string, unknown>;
  /** Execution status injected at render time. Defaults to "pending". */
  status?: DagNodeStatus;
}

export interface DagVisualizerProps {
  /** Array of task definitions (DAG JSON `tasks` array). */
  tasks: DagTask[];
}

// ---------------------------------------------------------------------------
// Status → visual styles
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<
  DagNodeStatus,
  { border: string; bg: string; text: string; dot: string }
> = {
  pending: {
    border: "border-gray-600",
    bg: "bg-gray-800",
    text: "text-gray-300",
    dot: "bg-gray-500",
  },
  running: {
    border: "border-indigo-500",
    bg: "bg-indigo-950",
    text: "text-indigo-200",
    dot: "bg-indigo-400 animate-pulse",
  },
  completed: {
    border: "border-emerald-500",
    bg: "bg-emerald-950",
    text: "text-emerald-200",
    dot: "bg-emerald-400",
  },
  failed: {
    border: "border-red-500",
    bg: "bg-red-950",
    text: "text-red-300",
    dot: "bg-red-500",
  },
};

// ---------------------------------------------------------------------------
// Custom node component
// ---------------------------------------------------------------------------

interface TaskNodeData {
  task_id: string;
  task_type: "Standard" | "Debate";
  label: string;
  status: DagNodeStatus;
}

function TaskNode({ data }: NodeProps<TaskNodeData>) {
  const styles = STATUS_STYLES[data.status];

  return (
    <div
      className={`
        min-w-[160px] rounded-lg border-2 px-4 py-3 shadow-lg
        ${styles.border} ${styles.bg}
      `}
    >
      {/* Top handle — dependency input */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-500 !border-gray-400 !w-2.5 !h-2.5"
      />

      {/* Header: status dot + task type badge */}
      <div className="flex items-center justify-between mb-1.5 gap-2">
        <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${styles.dot}`} />
        <span
          className={`
            text-xs font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded
            ${data.task_type === "Debate"
              ? "bg-purple-900/60 text-purple-300"
              : "bg-gray-700/60 text-gray-400"
            }
          `}
        >
          {data.task_type === "Debate" ? "ディベート" : "標準"}
        </span>
      </div>

      {/* Task label (role or task_id) */}
      <p className={`text-sm font-medium leading-snug ${styles.text}`}>
        {data.label}
      </p>

      {/* Task ID sub-label */}
      <p className="text-xs text-gray-600 mt-0.5 truncate">{data.task_id}</p>

      {/* Bottom handle — dependency output */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-500 !border-gray-400 !w-2.5 !h-2.5"
      />
    </div>
  );
}

// Register the custom node type (must be stable across renders — defined outside component)
const nodeTypes = { taskNode: TaskNode };

// ---------------------------------------------------------------------------
// Layout helpers — simple top-down layered layout
// ---------------------------------------------------------------------------

/**
 * Assigns a visual layer to each node using a longest-path DAG level assignment.
 * Nodes with no parents are placed at layer 0; each child is placed at
 * max(parent_layers) + 1.
 */
function computeLayers(tasks: DagTask[]): Map<string, number> {
  const layers = new Map<string, number>();
  const taskMap = new Map(tasks.map((t) => [t.task_id, t]));

  function layerOf(id: string): number {
    if (layers.has(id)) return layers.get(id)!;
    const task = taskMap.get(id);
    if (!task || task.parent_ids.length === 0) {
      layers.set(id, 0);
      return 0;
    }
    const layer = Math.max(...task.parent_ids.map(layerOf)) + 1;
    layers.set(id, layer);
    return layer;
  }

  tasks.forEach((t) => layerOf(t.task_id));
  return layers;
}

/**
 * Converts a tasks array into React Flow nodes and edges with a layered layout.
 * Each layer is rendered on a separate horizontal row (top-down flow).
 */
function buildGraph(tasks: DagTask[]): { nodes: Node[]; edges: Edge[] } {
  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 90;
  const H_GAP = 40;
  const V_GAP = 80;

  const layers = computeLayers(tasks);

  // Group task IDs by layer
  const byLayer = new Map<number, string[]>();
  layers.forEach((layer, id) => {
    if (!byLayer.has(layer)) byLayer.set(layer, []);
    byLayer.get(layer)!.push(id);
  });

  const taskMap = new Map(tasks.map((t) => [t.task_id, t]));
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  byLayer.forEach((ids, layer) => {
    const rowWidth = ids.length * NODE_WIDTH + (ids.length - 1) * H_GAP;
    ids.forEach((id, col) => {
      const task = taskMap.get(id)!;
      const status = task.status ?? "pending";
      const x = col * (NODE_WIDTH + H_GAP) - rowWidth / 2 + NODE_WIDTH / 2;
      const y = layer * (NODE_HEIGHT + V_GAP);

      nodes.push({
        id,
        type: "taskNode",
        position: { x, y },
        data: {
          task_id: task.task_id,
          task_type: task.task_type,
          label: task.role ?? task.participants?.join(", ") ?? task.task_id,
          status,
        } satisfies TaskNodeData,
      });

      // Create edges for each parent → this node dependency
      task.parent_ids.forEach((parentId) => {
        edges.push({
          id: `${parentId}->${id}`,
          source: parentId,
          target: id,
          animated: status === "running",
          markerEnd: { type: MarkerType.ArrowClosed, color: "#6b7280" },
          style: { stroke: "#6b7280" },
        });
      });
    });
  });

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export default function DagVisualizer({ tasks }: DagVisualizerProps) {
  if (!tasks || tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        DAGデータがありません。
      </div>
    );
  }

  const { nodes, edges } = buildGraph(tasks);

  return (
    <div className="w-full h-full" style={{ minHeight: 320 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#374151" gap={20} size={1} />
        <Controls className="[&>button]:bg-gray-800 [&>button]:border-gray-700 [&>button]:text-gray-300 [&>button:hover]:bg-gray-700" />
        <MiniMap
          nodeColor={(node) => {
            const status = (node.data as TaskNodeData).status;
            const colors: Record<DagNodeStatus, string> = {
              pending: "#6b7280",
              running: "#6366f1",
              completed: "#10b981",
              failed: "#ef4444",
            };
            return colors[status] ?? "#6b7280";
          }}
          className="!bg-gray-900 !border-gray-700"
        />
      </ReactFlow>

      {/* Status legend */}
      <div className="flex items-center gap-4 mt-3 px-1 flex-wrap">
        {(Object.entries(STATUS_STYLES) as [DagNodeStatus, typeof STATUS_STYLES[DagNodeStatus]][]).map(
          ([status, s]) => (
            <span key={status} className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className={`inline-block w-2.5 h-2.5 rounded-full ${s.dot.replace(" animate-pulse", "")}`} />
              {status === "pending" && "待機中"}
              {status === "running" && "実行中"}
              {status === "completed" && "完了"}
              {status === "failed" && "失敗"}
            </span>
          )
        )}
      </div>
    </div>
  );
}

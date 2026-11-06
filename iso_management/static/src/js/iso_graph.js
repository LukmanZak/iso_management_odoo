/** @odoo-module **/
import { Component, onMounted, onWillDestroy, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

const ROW = 30;
const CLAUSE_X = 16;
const EVIDENCE_X = 520;
const APP_X = 880;
const WIDTH = 1060;

const STATUS_LABELS = {
    covered: "Covered",
    partial: "Partial",
    gap: "Gap",
    unscanned: "Not scanned",
};

export class IsoGraph extends Component {
    static template = "iso_management.IsoGraph";
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.statusLabels = STATUS_LABELS;
        this.state = proxy({
            loading: true,
            running: 0,
            filter: "all",
            hover: null,
            data: null,
            layout: { clauses: [], evidence: [], apps: [], links: [], height: 200 },
        });
        let timer;
        onWillStart(() => this.load());
        onMounted(() => {
            timer = setInterval(async () => {
                const result = await this.orm.call("iso.management.scan", "get_progress", []);
                const running = result.running || 0;
                if (this.state.running && !running) {
                    await this.load();
                }
                this.state.running = running;
            }, 4000);
        });
        onWillDestroy(() => clearInterval(timer));
    }

    get standardId() {
        const params = this.props.action.params || {};
        return params.standard_id || false;
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("iso.management.standard", "get_graph_data", [this.standardId]);
        this.state.data = data;
        this.computeLayout();
        this.state.loading = false;
    }

    setFilter(filter) {
        this.state.filter = filter;
        this.computeLayout();
    }

    computeLayout() {
        const data = this.state.data;
        if (!data || !data.nodes.length) {
            this.state.layout = { clauses: [], evidence: [], apps: [], links: [], height: 200 };
            return;
        }
        const filter = this.state.filter;
        const nodesById = Object.fromEntries(data.nodes.map((n) => [n.id, n]));
        const evidenceByClause = {};
        const appByEvidence = {};
        for (const link of data.links) {
            if (link.type === "evidence") {
                (evidenceByClause[link.source] = evidenceByClause[link.source] || []).push(link.target);
            } else if (link.type === "source") {
                appByEvidence[link.source] = link.target;
            }
        }
        const visibleClause = (n) => filter === "all" || n.status === filter;
        const clauses = [];
        const evidence = [];
        const links = [];
        let row = 0;
        const clauseNodes = data.nodes.filter((n) => n.type === "clause");
        for (const node of clauseNodes) {
            if (!visibleClause(node)) {
                continue;
            }
            const evIds = node.is_leaf ? evidenceByClause[node.id] || [] : [];
            const span = Math.max(1, evIds.length);
            const y = (row + (span - 1) / 2) * ROW + ROW / 2;
            clauses.push({ ...node, x: CLAUSE_X + node.level * 14, y });
            evIds.forEach((evId, index) => {
                const ev = nodesById[evId];
                const ey = (row + index) * ROW + ROW / 2;
                evidence.push({ ...ev, x: EVIDENCE_X, y: ey, clauseId: node.id });
            });
            row += span;
        }
        const height = Math.max(row * ROW + 20, 120);
        // Position app nodes at the mean y of their evidence, then de-overlap.
        const apps = data.nodes.filter((n) => n.type === "app").map((app) => {
            const ys = evidence.filter((e) => appByEvidence[e.id] === app.id).map((e) => e.y);
            return { ...app, x: APP_X, y: ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null };
        }).filter((a) => a.y !== null).sort((a, b) => a.y - b.y);
        let last = -Infinity;
        for (const app of apps) {
            app.y = Math.max(app.y, last + ROW);
            last = app.y;
        }
        const pos = Object.fromEntries([...clauses, ...evidence, ...apps].map((n) => [n.id, n]));
        for (const link of data.links) {
            const a = pos[link.source];
            const b = pos[link.target];
            if (!a || !b) {
                continue;
            }
            if (link.type === "hierarchy") {
                const x1 = a.x + 4;
                links.push({ ...link, key: link.source + link.target, d: `M${x1},${a.y + 6} V${b.y} H${b.x - 4}` });
            } else if (link.type === "evidence") {
                links.push({ ...link, key: link.source + link.target, d: `M${a.x + 330},${a.y} C${EVIDENCE_X - 60},${a.y} ${EVIDENCE_X - 60},${b.y} ${b.x - 6},${b.y}` });
            } else {
                links.push({ ...link, key: link.source + link.target, d: `M${a.x + 250},${a.y} C${APP_X - 70},${a.y} ${APP_X - 70},${b.y} ${b.x - 6},${b.y}` });
            }
        }
        const height2 = Math.max(height, (apps.length ? apps[apps.length - 1].y + ROW : 0));
        this.state.layout = { clauses, evidence, apps, links, height: height2 };
    }

    // -- interaction ------------------------------------------------------
    isDim(id) {
        const hover = this.state.hover;
        if (!hover) {
            return false;
        }
        return !this.connected(hover).has(id);
    }

    linkDim(link) {
        const hover = this.state.hover;
        if (!hover) {
            return false;
        }
        const reach = this.connected(hover);
        return !(reach.has(link.source) && reach.has(link.target));
    }

    connected(id) {
        const result = new Set([id]);
        const links = this.state.layout.links;
        // two hops so a clause highlights its evidence and their apps
        for (let hop = 0; hop < 2; hop++) {
            for (const link of links) {
                if (link.type === "hierarchy" && hop > 0) {
                    continue;
                }
                if (result.has(link.source)) {
                    result.add(link.target);
                } else if (result.has(link.target) && hop === 0) {
                    result.add(link.source);
                }
            }
        }
        return result;
    }

    hoverNode(id) {
        this.state.hover = id;
    }

    clipLabel(text, max) {
        return text && text.length > max ? text.slice(0, max - 1) + "…" : text || "";
    }

    openNode(node) {
        if (node.type === "app") {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: node.res_model,
            res_id: node.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openSource(node) {
        if (node.source_model && node.source_record_id) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: node.source_model,
                res_id: node.source_record_id,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    async runAll(provider) {
        const method = provider === "rag" ? "action_run_all_rag" : "action_run_all";
        try {
            await this.orm.call("iso.management.standard", method, [[this.state.data.standard.id]]);
            this.state.running = 1;
            this.notification.add("Detection queued. The graph refreshes when the worker finishes.", { type: "info" });
        } catch (error) {
            this.notification.add(error.data?.message || "Could not start detection.", { type: "danger" });
        }
    }
}

registry.category("actions").add("iso_graph", IsoGraph);

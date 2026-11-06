/** @odoo-module **/
import { Component, onMounted, onWillDestroy, proxy, useProps } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        this.isoProgress = proxy({ running: 0 });
        const orm = useService("orm");
        let timer;
        const refresh = async () => {
            try {
                const result = await orm.call("iso.management.scan", "get_progress", []);
                this.isoProgress.running = result.running || 0;
            } catch {
                this.isoProgress.running = 0;
            }
        };
        onMounted(() => { refresh(); timer = setInterval(refresh, 5000); });
        onWillDestroy(() => clearInterval(timer));
    },
});

class ScanProgress extends Component {
    static template = "iso_management.ScanProgress";
    props = useProps({ ...standardFieldProps });
    progress = proxy({ state: "", label: "", captured: 0, waiting: 0, failed: 0 });

    setup() {
        this.orm = useService("orm");
        this.previousState = this.props.record.data.execution_state || "";
        let timer;
        const refresh = async () => {
            const id = this.props.record.resId;
            if (!id) return;
            try {
                const data = await this.orm.call("iso.management.scan", "get_progress", [id]);
                if (!data) return;
                const previous = this.previousState;
                Object.assign(this.progress, data);
                this.previousState = data.state;
                if (["queued", "running", "capturing"].includes(previous) && previous !== data.state && !(await this.props.record.isDirty())) {
                    await this.props.record.load();
                }
            } catch {
                // Keep the last known state while the server is unavailable.
            }
        };
        onMounted(() => { refresh(); timer = setInterval(refresh, 5000); });
        onWillDestroy(() => clearInterval(timer));
    }
}

registry.category("fields").add("iso_scan_progress", { component: ScanProgress, supportedTypes: ["char"] });

import apiClient from './api';

export interface JobLog {
    id: number;
    job_type: string;
    job_id: number;
    node_name: string;
    dataset: string;
    status: string;
    message: string;
    output: string;
    error: string;
    duration: number;
    transferred: string;
    attempt_number: number;
    started_at: string;
    completed_at: string;
    triggered_by: number;
}

export default {
    getLogs(params: {
        limit?: number;
        offset?: number;
        job_type?: string;
        status?: string;
        job_id?: number | string;
    }) {
        return apiClient.get<JobLog[]>('/logs/', { params });
    },

    getLog(id: number) {
        return apiClient.get<JobLog>(`/logs/${id}`);
    },

    getJobHistory(jobId: number | string, limit: number = 50) {
        return apiClient.get<JobLog[]>(`/logs/job/${jobId}/history`, { params: { limit } });
    }
}

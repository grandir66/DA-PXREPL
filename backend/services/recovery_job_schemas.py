"""Pydantic schemas per recovery jobs PBS."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RecoveryJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Nome identificativo del job")
    source_node_id: int = Field(..., gt=0, description="ID nodo sorgente (PVE)")
    vm_id: int = Field(..., gt=0, le=999999, description="VMID della VM da replicare (1-999999)")
    vm_type: str = Field(default="qemu", pattern="^(qemu|lxc)$", description="Tipo VM: qemu o lxc")
    vm_name: Optional[str] = Field(None, max_length=100, description="Nome VM (opzionale)")
    pbs_node_id: int = Field(..., gt=0, description="ID nodo PBS")
    pbs_datastore: Optional[str] = Field(None, max_length=100, description="Datastore PBS (override)")
    pbs_storage_id: Optional[str] = Field(None, max_length=100, description="Nome storage PBS configurato sul nodo")
    dest_node_id: int = Field(..., gt=0, description="ID nodo destinazione (PVE)")
    dest_vm_id: Optional[int] = Field(None, gt=0, le=999999, description="VMID destinazione (opzionale)")
    dest_vm_name_suffix: Optional[str] = Field(None, max_length=50, description="Suffisso nome VM (es: '-replica')")
    dest_storage: Optional[str] = Field(None, max_length=100, description="Storage destinazione")
    backup_mode: str = Field(default="snapshot", pattern="^(snapshot|stop|suspend)$", description="Modalità backup")
    backup_compress: str = Field(default="zstd", pattern="^(none|lzo|gzip|zstd)$", description="Compressione backup")
    include_all_disks: bool = Field(default=True, description="Includi tutti i dischi")
    restore_start_vm: bool = Field(default=False, description="Avvia VM dopo restore")
    restore_unique: bool = Field(default=True, description="Genera nuovi UUID")
    overwrite_existing: bool = Field(default=True, description="Sovrascrivi se esiste")
    schedule: Optional[str] = Field(None, max_length=100, description="Schedule cron per recovery completo")
    schedule_config: Optional[Dict[str, Any]] = Field(None, description="Struttura JSON 'human' di schedule (vedi schedule_translator)")
    backup_schedule: Optional[str] = Field(None, max_length=100, description="Schedule cron per backup (opzionale)")
    is_active: bool = Field(default=True, description="Job attivo")
    retry_on_failure: bool = Field(default=True, description="Retry automatico su fallimento")
    max_retries: int = Field(default=3, ge=0, le=10, description="Numero massimo retry (0-10)")
    retry_delay_minutes: int = Field(default=15, ge=1, le=1440, description="Ritardo tra retry in minuti (1-1440)")
    notify_on_each_run: bool = Field(default=False, description="Notifica ad ogni esecuzione (altrimenti solo report giornaliero)")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valida nome: solo caratteri alfanumerici, spazi, trattini e underscore"""
        if not re.match(r'^[a-zA-Z0-9\s_-]+$', v):
            raise ValueError("Nome può contenere solo lettere, numeri, spazi, trattini e underscore")
        return v.strip()
    
    @field_validator('schedule', 'backup_schedule')
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        """Valida formato cron base (5 campi)"""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        # Verifica formato cron base: 5 campi separati da spazio
        parts = v.split()
        if len(parts) != 5:
            raise ValueError("Schedule deve essere in formato cron (5 campi: minuto ora giorno mese giorno_settimana)")
        # Verifica range valori base
        try:
            minute = parts[0]
            hour = parts[1]
            day = parts[2]
            month = parts[3]
            weekday = parts[4]
            
            # Valori validi per ogni campo (semplificato)
            if minute not in ['*', '*/1', '*/5', '*/10', '*/15', '*/30'] and not minute.isdigit():
                if not (minute.isdigit() and 0 <= int(minute) <= 59):
                    raise ValueError("Minuto non valido (0-59 o */N)")
            if hour != '*' and not hour.startswith('*/') and not (hour.isdigit() and 0 <= int(hour) <= 23):
                raise ValueError("Ora non valida (0-23)")
        except (ValueError, IndexError) as e:
            raise ValueError(f"Formato cron non valido: {str(e)}")
        return v
    
    @field_validator('dest_vm_name_suffix')
    @classmethod
    def validate_suffix(cls, v: Optional[str]) -> Optional[str]:
        """Valida suffisso nome VM"""
        if v is None:
            return v
        v = v.strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Suffisso può contenere solo lettere, numeri, trattini e underscore")
        return v
    
    @model_validator(mode='after')
    def validate_nodes_different(self):
        """Verifica che i nodi siano diversi"""
        if self.source_node_id == self.dest_node_id:
            raise ValueError("Nodo sorgente e destinazione devono essere diversi")
        return self


class RecoveryJobUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    vm_name: Optional[str] = Field(None, max_length=100)
    pbs_datastore: Optional[str] = Field(None, max_length=100)
    pbs_storage_id: Optional[str] = Field(None, max_length=100)
    dest_vm_id: Optional[int] = Field(None, gt=0, le=999999)
    dest_vm_name_suffix: Optional[str] = Field(None, max_length=50)
    dest_storage: Optional[str] = Field(None, max_length=100)
    backup_mode: Optional[str] = Field(None, pattern="^(snapshot|stop|suspend)$")
    backup_compress: Optional[str] = Field(None, pattern="^(none|lzo|gzip|zstd)$")
    include_all_disks: Optional[bool] = None
    restore_start_vm: Optional[bool] = None
    restore_unique: Optional[bool] = None
    overwrite_existing: Optional[bool] = None
    schedule: Optional[str] = Field(None, max_length=100)
    schedule_config: Optional[Dict[str, Any]] = None
    backup_schedule: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    retry_on_failure: Optional[bool] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    retry_delay_minutes: Optional[int] = Field(None, ge=1, le=1440)
    notify_on_each_run: Optional[bool] = None


class RecoveryJobResponse(BaseModel):
    id: int
    name: str
    source_node_id: int
    vm_id: int
    vm_type: str
    vm_name: Optional[str]
    pbs_node_id: int
    pbs_datastore: Optional[str]
    pbs_storage_id: Optional[str]
    dest_node_id: int
    dest_vm_id: Optional[int]
    dest_vm_name_suffix: Optional[str]
    dest_storage: Optional[str]
    backup_mode: str
    backup_compress: str
    include_all_disks: bool
    restore_start_vm: bool
    restore_unique: bool
    overwrite_existing: bool
    schedule: Optional[str]
    schedule_config: Optional[Dict[str, Any]] = None
    backup_schedule: Optional[str]
    is_active: bool
    current_status: str
    last_backup_time: Optional[datetime]
    last_backup_id: Optional[str]
    last_restore_time: Optional[datetime]
    last_run: Optional[datetime]
    last_status: Optional[str]
    last_duration: Optional[int]
    last_error: Optional[str]
    run_count: int
    error_count: int
    consecutive_failures: int
    retry_on_failure: bool
    max_retries: int
    retry_delay_minutes: int
    notify_on_each_run: bool
    created_at: datetime
    # Campi extra per UI
    source_node_name: Optional[str] = None
    pbs_node_name: Optional[str] = None
    dest_node_name: Optional[str] = None
    # Durate delle ultime fasi (calcolate dai log)
    last_backup_duration: Optional[int] = None
    last_restore_duration: Optional[int] = None
    
    class Config:
        from_attributes = True


class PBSNodeInfo(BaseModel):
    """Info su un nodo PBS"""
    id: int
    name: str
    hostname: str
    pbs_available: bool
    pbs_version: Optional[str]
    pbs_datastore: Optional[str]
    datastores: List[str] = []


class BackupInfo(BaseModel):
    """Info su un backup PBS"""
    backup_id: str
    vm_id: int
    backup_time: datetime
    size: Optional[str]
    datastore: str


class DirectRestoreRequest(BaseModel):
    """Richiesta di restore diretto da un backup PBS esistente"""
    pbs_node_id: int = Field(..., gt=0, description="ID nodo PBS sorgente")
    backup_id: str = Field(..., min_length=1, description="ID del backup PBS")
    dest_node_id: int = Field(..., gt=0, description="ID nodo PVE destinazione")
    dest_vmid: Optional[int] = Field(None, gt=0, le=999999, description="VMID destinazione (opzionale)")
    dest_storage: Optional[str] = Field(None, description="Storage destinazione (opzionale)")
    vm_type: str = Field(default="qemu", pattern="^(qemu|lxc)$", description="Tipo VM")

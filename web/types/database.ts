export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  graphql_public: {
    Tables: {
      [_ in never]: never
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      graphql: {
        Args: {
          extensions?: Json
          operationName?: string
          query?: string
          variables?: Json
        }
        Returns: Json
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
  public: {
    Tables: {
      drones: {
        Row: {
          created_at: string
          id: string
          name: string
          notes: string | null
          uri: string
        }
        Insert: {
          created_at?: string
          id?: string
          name: string
          notes?: string | null
          uri?: string
        }
        Update: {
          created_at?: string
          id?: string
          name?: string
          notes?: string | null
          uri?: string
        }
        Relationships: []
      }
      flights: {
        Row: {
          ambient_start: number | null
          created_by: string | null
          csv_path: string | null
          drone_id: string | null
          ended_at: string | null
          error: string | null
          ground_z_m: number | null
          id: string
          started_at: string
          status: Database["public"]["Enums"]["flight_status"]
          temp_unit: string
        }
        Insert: {
          ambient_start?: number | null
          created_by?: string | null
          csv_path?: string | null
          drone_id?: string | null
          ended_at?: string | null
          error?: string | null
          ground_z_m?: number | null
          id?: string
          started_at?: string
          status?: Database["public"]["Enums"]["flight_status"]
          temp_unit?: string
        }
        Update: {
          ambient_start?: number | null
          created_by?: string | null
          csv_path?: string | null
          drone_id?: string | null
          ended_at?: string | null
          error?: string | null
          ground_z_m?: number | null
          id?: string
          started_at?: string
          status?: Database["public"]["Enums"]["flight_status"]
          temp_unit?: string
        }
        Relationships: [
          {
            foreignKeyName: "flights_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "flights_drone_id_fkey"
            columns: ["drone_id"]
            isOneToOne: false
            referencedRelation: "drones"
            referencedColumns: ["id"]
          },
        ]
      }
      missions: {
        Row: {
          claimed_at: string | null
          claimed_by: string | null
          created_at: string
          created_by: string | null
          error: string | null
          flight_id: string | null
          id: string
          name: string
          plan: Json
          status: Database["public"]["Enums"]["mission_status"]
          type: string
          updated_at: string
        }
        Insert: {
          claimed_at?: string | null
          claimed_by?: string | null
          created_at?: string
          created_by?: string | null
          error?: string | null
          flight_id?: string | null
          id?: string
          name?: string
          plan: Json
          status?: Database["public"]["Enums"]["mission_status"]
          type: string
          updated_at?: string
        }
        Update: {
          claimed_at?: string | null
          claimed_by?: string | null
          created_at?: string
          created_by?: string | null
          error?: string | null
          flight_id?: string | null
          id?: string
          name?: string
          plan?: Json
          status?: Database["public"]["Enums"]["mission_status"]
          type?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "missions_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "missions_flight_id_fkey"
            columns: ["flight_id"]
            isOneToOne: false
            referencedRelation: "flights"
            referencedColumns: ["id"]
          },
        ]
      }
      predictions: {
        Row: {
          created_at: string
          disease_risk: number | null
          flight_id: string
          health_score: number | null
          id: string
          label: string | null
          model: string
          notes: string | null
          sample_count: number | null
          zone_id: string | null
        }
        Insert: {
          created_at?: string
          disease_risk?: number | null
          flight_id: string
          health_score?: number | null
          id?: string
          label?: string | null
          model?: string
          notes?: string | null
          sample_count?: number | null
          zone_id?: string | null
        }
        Update: {
          created_at?: string
          disease_risk?: number | null
          flight_id?: string
          health_score?: number | null
          id?: string
          label?: string | null
          model?: string
          notes?: string | null
          sample_count?: number | null
          zone_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "predictions_flight_id_fkey"
            columns: ["flight_id"]
            isOneToOne: false
            referencedRelation: "flights"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "predictions_zone_id_fkey"
            columns: ["zone_id"]
            isOneToOne: false
            referencedRelation: "zones"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          created_at: string
          email: string
          full_name: string | null
          id: string
          role: string
        }
        Insert: {
          created_at?: string
          email: string
          full_name?: string | null
          id: string
          role?: string
        }
        Update: {
          created_at?: string
          email?: string
          full_name?: string | null
          id?: string
          role?: string
        }
        Relationships: []
      }
      telemetry: {
        Row: {
          air_density_kg_m3: number | null
          ambient_est: number | null
          battery_v: number | null
          corrected_temp: number | null
          deviation: number | null
          event: string | null
          expected_raw: number | null
          flight_id: string
          id: number
          index: number
          mode: string | null
          pressure_altitude_m: number | null
          raw_temp: number | null
          recorded_at: string
          roc_per_s: number | null
          sea_level_pressure_hpa: number | null
          station_pressure_hpa: number | null
          temp_unit: string
          thermal_offset: number | null
          thermal_state: string | null
          thrust: number | null
          x_m: number | null
          y_m: number | null
          z_m: number | null
        }
        Insert: {
          air_density_kg_m3?: number | null
          ambient_est?: number | null
          battery_v?: number | null
          corrected_temp?: number | null
          deviation?: number | null
          event?: string | null
          expected_raw?: number | null
          flight_id: string
          id?: number
          index: number
          mode?: string | null
          pressure_altitude_m?: number | null
          raw_temp?: number | null
          recorded_at: string
          roc_per_s?: number | null
          sea_level_pressure_hpa?: number | null
          station_pressure_hpa?: number | null
          temp_unit: string
          thermal_offset?: number | null
          thermal_state?: string | null
          thrust?: number | null
          x_m?: number | null
          y_m?: number | null
          z_m?: number | null
        }
        Update: {
          air_density_kg_m3?: number | null
          ambient_est?: number | null
          battery_v?: number | null
          corrected_temp?: number | null
          deviation?: number | null
          event?: string | null
          expected_raw?: number | null
          flight_id?: string
          id?: number
          index?: number
          mode?: string | null
          pressure_altitude_m?: number | null
          raw_temp?: number | null
          recorded_at?: string
          roc_per_s?: number | null
          sea_level_pressure_hpa?: number | null
          station_pressure_hpa?: number | null
          temp_unit?: string
          thermal_offset?: number | null
          thermal_state?: string | null
          thrust?: number | null
          x_m?: number | null
          y_m?: number | null
          z_m?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "telemetry_flight_id_fkey"
            columns: ["flight_id"]
            isOneToOne: false
            referencedRelation: "flights"
            referencedColumns: ["id"]
          },
        ]
      }
      zones: {
        Row: {
          created_at: string
          id: string
          label: string
          x_max: number
          x_min: number
          y_max: number
          y_min: number
        }
        Insert: {
          created_at?: string
          id?: string
          label: string
          x_max: number
          x_min: number
          y_max: number
          y_min: number
        }
        Update: {
          created_at?: string
          id?: string
          label?: string
          x_max?: number
          x_min?: number
          y_max?: number
          y_min?: number
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      claim_next_mission: {
        Args: { agent_id: string }
        Returns: {
          claimed_at: string | null
          claimed_by: string | null
          created_at: string
          created_by: string | null
          error: string | null
          flight_id: string | null
          id: string
          name: string
          plan: Json
          status: Database["public"]["Enums"]["mission_status"]
          type: string
          updated_at: string
        }
        SetofOptions: {
          from: "*"
          to: "missions"
          isOneToOne: true
          isSetofReturn: false
        }
      }
      is_operator: { Args: never; Returns: boolean }
      release_stale_claims: { Args: { older_than?: string }; Returns: number }
    }
    Enums: {
      flight_status: "running" | "completed" | "aborted" | "failed"
      mission_status:
        | "queued"
        | "claimed"
        | "running"
        | "done"
        | "failed"
        | "cancelled"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  graphql_public: {
    Enums: {},
  },
  public: {
    Enums: {
      flight_status: ["running", "completed", "aborted", "failed"],
      mission_status: [
        "queued",
        "claimed",
        "running",
        "done",
        "failed",
        "cancelled",
      ],
    },
  },
} as const


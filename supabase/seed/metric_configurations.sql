INSERT INTO metric_configurations (metric_key, display_label, is_client_visible, display_order, description, threshold_config)
VALUES
  (
    'delivery_confidence',
    'Delivery Confidence',
    true,
    1,
    'Current schedule confidence for the active milestone.',
    NULL
  ),
  (
    'throughput_rolling_7d',
    '7-Day Throughput',
    true,
    2,
    'Rolling seven-day completed unit volume.',
    NULL
  ),
  (
    'gold_set_accuracy',
    'Gold-Set Accuracy',
    true,
    3,
    'Weekly quality accuracy against gold-set labels.',
    '{"green_min": 96.0, "amber_min": 94.0, "red_min": 92.0, "wow_drop_amber": 1.0, "wow_drop_red": 2.0, "wow_drop_critical": 4.0, "direction": "higher_is_better"}'::jsonb
  ),
  (
    'iaa_krippendorff_alpha',
    'Inter-Annotator Agreement',
    false,
    5,
    'Krippendorff alpha agreement score.',
    '{"green_min": 0.90, "amber_min": 0.85, "red_min": 0.80, "wow_drop_amber": 0.03, "wow_drop_red": 0.05, "wow_drop_critical": 0.08, "direction": "higher_is_better"}'::jsonb
  ),
  (
    'rework_rate',
    'Rework Rate',
    true,
    4,
    'Weekly percentage of work requiring rework.',
    '{"green_max": 3.0, "amber_max": 4.0, "red_max": 6.0, "wow_rise_amber": 1.0, "wow_rise_red": 2.0, "wow_rise_critical": 4.0, "direction": "lower_is_better"}'::jsonb
  )
ON CONFLICT (metric_key) DO UPDATE SET
  display_label = EXCLUDED.display_label,
  is_client_visible = EXCLUDED.is_client_visible,
  display_order = EXCLUDED.display_order,
  description = EXCLUDED.description,
  threshold_config = COALESCE(EXCLUDED.threshold_config, metric_configurations.threshold_config);

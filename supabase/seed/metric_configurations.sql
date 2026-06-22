INSERT INTO metric_configurations (metric_key, display_label, is_client_visible, display_order, description)
VALUES
  ('delivery_confidence', 'Delivery Confidence', true, 1, 'Current schedule confidence for the active milestone.'),
  ('throughput_rolling_7d', '7-Day Throughput', true, 2, 'Rolling seven-day completed unit volume.'),
  ('gold_set_accuracy', 'Gold-Set Accuracy', true, 3, 'Weekly quality accuracy against gold-set labels.'),
  ('rework_rate', 'Rework Rate', true, 4, 'Weekly percentage of work requiring rework.')
ON CONFLICT (metric_key) DO UPDATE SET
  display_label = EXCLUDED.display_label,
  is_client_visible = EXCLUDED.is_client_visible,
  display_order = EXCLUDED.display_order,
  description = EXCLUDED.description;

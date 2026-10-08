package com.zoneroffers.swiggypalace;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/telegram")
public class TelegramWebhookController {
 private final BotService bot;
 public TelegramWebhookController(BotService bot){this.bot=bot;}
 @PostMapping("/webhook")
 public ResponseEntity<Void> webhook(@RequestBody JsonNode update){bot.accept(update);return ResponseEntity.ok().build();}
}
package com.zoneroffers.swiggypalace;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.Map;
@RestController
public class HealthController {
 private final BotProperties props;
 public HealthController(BotProperties props){this.props=props;}
 @GetMapping({"/","/health"})
 public Map<String,Object> health(){return Map.of("status","ok","service","swiggy-palace-bot","mode","telegram-webhook","configured",!props.getToken().isBlank());}
}
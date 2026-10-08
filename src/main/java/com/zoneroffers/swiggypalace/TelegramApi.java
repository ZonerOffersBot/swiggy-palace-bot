package com.zoneroffers.swiggypalace;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

@Service
public class TelegramApi {
 private final BotProperties props;
 private final ObjectMapper mapper;
 private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();

 public TelegramApi(BotProperties props,ObjectMapper mapper){this.props=props;this.mapper=mapper;}

 public JsonNode call(String method,Map<String,Object> body){
  if(props.getToken().isBlank()) throw new IllegalStateException("BOT_TOKEN is not configured");
  try{
   String json=mapper.writeValueAsString(body==null?Map.of():body);
   HttpRequest req=HttpRequest.newBuilder()
     .uri(URI.create("https://api.telegram.org/bot"+props.getToken()+"/"+method))
     .timeout(Duration.ofSeconds(45))
     .header("Content-Type","application/json")
     .POST(HttpRequest.BodyPublishers.ofString(json)).build();
   HttpResponse<String> res=http.send(req,HttpResponse.BodyHandlers.ofString());
   JsonNode node=mapper.readTree(res.body());
   if(res.statusCode()<200||res.statusCode()>=300||!node.path("ok").asBoolean(false))
    throw new TelegramApiException(res.statusCode(),node.path("description").asText("Telegram API error"));
   return node.path("result");
  }catch(TelegramApiException e){throw e;}
  catch(Exception e){throw new RuntimeException("Telegram API request failed: "+method,e);}
 }

 public void sendMessage(long chatId,String text,String replyMarkup){
  try{
   Map<String,Object> b=new HashMap<>();
   b.put("chat_id",chatId); b.put("text",text); b.put("parse_mode","HTML");
   if(replyMarkup!=null&&!replyMarkup.isBlank()) b.put("reply_markup",mapper.readTree(replyMarkup));
   call("sendMessage",b);
  }catch(Exception e){throw new RuntimeException(e);}
 }

 public void answerCallback(String id){
  if(id==null||id.isBlank())return;
  try{call("answerCallbackQuery",Map.of("callback_query_id",id));}catch(Exception ignored){}
 }

 public void setWebhook(String url){call("setWebhook",Map.of("url",url,"drop_pending_updates",false));}

 public static class TelegramApiException extends RuntimeException{
  private final int status;
  public TelegramApiException(int status,String message){super(message);this.status=status;}
  public int getStatus(){return status;}
 }
}
